"""
Contact Extraction Engine

Orchestrates the process of reading job scraper CSV outputs and enriching them
with CEO/CTO contact information using the ExecutiveContactFinder agent.
"""

import os
import csv
import json
import time
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv

from agent import ExecutiveContactFinder, ContactInfo

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ContactExtractor:
    """
    Main orchestrator for extracting executive contacts from job listings
    """
    
    def __init__(self, input_csv_path: str, output_dir: str = "scraper_outputs"):
        """
        Initialize the contact extractor
        
        Args:
            input_csv_path: Path to the input CSV file
            output_dir: Directory to save enriched output CSV
        """
        self.input_csv_path = input_csv_path
        self.output_dir = output_dir
        self.finder = ExecutiveContactFinder()
        self.cache = {}  # In-process cache to avoid duplicate searches
        self.stats = {
            "total_companies": 0,
            "processable_companies": 0,
            "skipped_placeholder_companies": 0,
            "contacts_found": 0,
            "contacts_not_found": 0,
            "api_calls": 0,
            "processing_time": 0
        }

    @staticmethod
    def _is_placeholder_company(company_name: str) -> bool:
        """Return True when company name looks like a scraper placeholder value."""
        if not company_name:
            return True
        value = str(company_name).strip().lower()
        return value.startswith("company_") or value in {"n/a", "none", "unknown", "-"}

    @staticmethod
    def _empty_contact_result(company_name: str, reason: str) -> Dict[str, Any]:
        """Build a consistent empty contact payload for skipped or failed lookups."""
        return {
            "company_name": company_name,
            "ceo": ContactInfo().to_dict(),
            "cto": ContactInfo().to_dict(),
            "search_status": "not_found",
            "search_attempts": 0,
            "search_confidence": 0.0,
            "search_reason": reason,
        }
    
    def extract_contacts(self, sample_size: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Extract executive contacts from input CSV
        
        Args:
            sample_size: Optional limit on number of companies to process
        
        Returns:
            List of enriched company records with contact information
        """
        logger.info(f"Reading CSV from: {self.input_csv_path}")
        
        # Read the input CSV
        try:
            df = pd.read_csv(self.input_csv_path)
        except FileNotFoundError:
            logger.error(f"Input CSV not found: {self.input_csv_path}")
            return []
        
        if df.empty:
            logger.warning("Input CSV is empty")
            return []
        
        logger.info(f"Found {len(df)} records in CSV")
        
        # Limit sample size if specified
        if sample_size:
            df = df.head(sample_size)
            logger.info(f"Processing sample of {sample_size} records")
        
        # Determine source company column
        company_col = 'company' if 'company' in df.columns else df.columns[0]

        # Keep all unique companies for stats, then filter processable values.
        companies = (
            df[[company_col]]
            .dropna()
            .drop_duplicates()
            .rename(columns={company_col: 'company'})
        )
        self.stats["total_companies"] = len(companies)

        placeholder_mask = companies['company'].apply(self._is_placeholder_company)
        self.stats["skipped_placeholder_companies"] = int(placeholder_mask.sum())
        processable_companies = companies[~placeholder_mask].reset_index(drop=True)
        self.stats["processable_companies"] = len(processable_companies)

        logger.info(
            "Processing %s unique companies (%s skipped placeholders)",
            len(processable_companies),
            self.stats["skipped_placeholder_companies"],
        )
        
        enriched_records = []
        start_time = time.time()
        
        # Pre-fill placeholders with empty result to avoid low-quality lookups and wasted API calls.
        for skipped_company in companies[placeholder_mask]['company'].tolist():
            self.cache[skipped_company] = self._empty_contact_result(
                skipped_company,
                "placeholder_company_name",
            )
            self.stats["contacts_not_found"] += 1

        for idx, company_row in processable_companies.iterrows():
            company_name = company_row['company']
            
            # Check cache first
            if company_name in self.cache:
                logger.info(f"[Cache] Using cached data for: {company_name}")
                contact_data = self.cache[company_name]
            else:
                # Search for contacts
                logger.info(f"[{idx+1}/{len(processable_companies)}] Searching contacts for: {company_name}")
                contact_data = self.finder.find_executive_contacts(company_name)
                if "search_reason" not in contact_data:
                    contact_data["search_reason"] = "searched"
                self.cache[company_name] = contact_data
                self.stats["api_calls"] += contact_data.get("search_attempts", 0)
                
                # Update stats
                if contact_data["search_status"] == "found":
                    self.stats["contacts_found"] += 1
                else:
                    self.stats["contacts_not_found"] += 1
            
        # Enrich every original row using cached company results so no rows are dropped.
        for _, row in df.iterrows():
            record = row.to_dict()
            company_name = record.get(company_col, "")
            contact_data = self.cache.get(
                company_name,
                self._empty_contact_result(company_name, "missing_company_name"),
            )
            enriched = {**record, **contact_data}
            enriched_records.append(enriched)
        
        self.stats["processing_time"] = time.time() - start_time
        
        logger.info(f"Processing completed in {self.stats['processing_time']:.2f}s")
        logger.info(f"Contacts found: {self.stats['contacts_found']}/{self.stats['total_companies']}")
        
        return enriched_records

    @staticmethod
    def _to_compact_row(record: Dict[str, Any]) -> Dict[str, Any]:
        """Convert an enriched row to a compact, analytics-friendly schema."""
        ceo = record.get("ceo", {}) or {}
        cto = record.get("cto", {}) or {}
        return {
            "wantedly_project_id": record.get("wantedly_project_id", ""),
            "url": record.get("url", ""),
            "company": record.get("company", record.get("company_name", "")),
            "title": record.get("title", ""),
            "ceo_name": ceo.get("name", ""),
            "ceo_title": ceo.get("title", ""),
            "ceo_email": ceo.get("email", ""),
            "ceo_linkedin_url": ceo.get("linkedin_url", ""),
            "cto_name": cto.get("name", ""),
            "cto_title": cto.get("title", ""),
            "cto_email": cto.get("email", ""),
            "cto_linkedin_url": cto.get("linkedin_url", ""),
            "search_status": record.get("search_status", "not_found"),
            "search_confidence": record.get("search_confidence", 0.0),
            "search_reason": record.get("search_reason", ""),
        }
    
    def save_enriched_csv(self, enriched_records: List[Dict[str, Any]]) -> str:
        """
        Save enriched records to output CSV
        
        Args:
            enriched_records: List of enriched company records
        
        Returns:
            Path to the output CSV file
        """
        if not enriched_records:
            logger.warning("No records to save")
            return None
        
        # Create output directory if it doesn't exist
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        
        # Generate output filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        input_stem = Path(self.input_csv_path).stem
        output_filename = f"{input_stem}_with_contacts_{timestamp}.csv"
        output_path = os.path.join(self.output_dir, output_filename)
        
        # Save compact CSV (only high-value columns, no nested dict columns)
        try:
            compact_rows = [self._to_compact_row(r) for r in enriched_records]
            df = pd.DataFrame(compact_rows)
            df.to_csv(output_path, index=False)
            logger.info(f"Enriched CSV saved to: {output_path}")
        except Exception as e:
            logger.error(f"Failed to save enriched CSV: {str(e)}")
            return None
        
        return output_path
    
    def save_stats(self) -> Dict[str, Any]:
        """
        Save processing statistics
        
        Returns:
            Statistics dictionary
        """
        stats_with_metadata = {
            **self.stats,
            "timestamp": datetime.now().isoformat(),
            "cache_size": len(self.cache)
        }
        
        logger.info("Processing Statistics:")
        for key, value in stats_with_metadata.items():
            logger.info(f"  {key}: {value}")
        
        return stats_with_metadata


def main(input_csv: str, output_dir: str = "scraper_outputs", sample_size: Optional[int] = None):
    """
    Main entry point for contact extraction
    
    Args:
        input_csv: Path to input CSV file
        output_dir: Directory for output CSV
        sample_size: Optional limit on records to process
    """
    logger.info("Starting Contact Extraction Agent")
    
    extractor = ContactExtractor(input_csv, output_dir)
    
    # Extract contacts
    enriched_records = extractor.extract_contacts(sample_size=sample_size)
    
    if enriched_records:
        # Save enriched CSV
        output_path = extractor.save_enriched_csv(enriched_records)
        
        # Save stats
        stats = extractor.save_stats()
        
        logger.info(f"✓ Successfully processed {len(enriched_records)} records")
        logger.info(f"✓ Output saved to: {output_path}")
    else:
        logger.warning("No records were enriched")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python contact_extractor.py <input_csv> [output_dir] [sample_size]")
        print("Example: python contact_extractor.py scraper_outputs/wantedly_Ruby_on_Rails_Japan.csv scraper_outputs 10")
        sys.exit(1)
    
    input_csv = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "scraper_outputs"
    sample_size = int(sys.argv[3]) if len(sys.argv) > 3 else None
    
    main(input_csv, output_dir, sample_size)
