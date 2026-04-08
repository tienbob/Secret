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
import re
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

import pandas as pd
from dotenv import load_dotenv

from agent import ExecutiveContactFinder, ContactInfo

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ContactExtractionCancelled(Exception):
    """Raised when a contact extraction job is cancelled by user request."""


class ContactExtractor:
    """
    Main orchestrator for extracting executive contacts from job listings
    """
    
    def __init__(self, input_csv_path: str, output_dir: str = "scraper_outputs", should_cancel=None):
        """
        Initialize the contact extractor
        
        Args:
            input_csv_path: Path to the input CSV file
            output_dir: Directory to save enriched output CSV
        """
        self.input_csv_path = input_csv_path
        self.output_dir = output_dir
        self.finder = ExecutiveContactFinder()
        self.should_cancel = should_cancel
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

    @staticmethod
    def _resolve_company_column(df: pd.DataFrame) -> Optional[str]:
        """Return the best company-name column from known schema variants."""
        candidates = [
            "company",
            "company_name",
            "employer",
            "organization",
            "company_slug",
        ]
        for col in candidates:
            if col in df.columns:
                return col
        return None

    @staticmethod
    def _derive_company_from_website(url: str) -> str:
        """Infer a readable company token from a website URL hostname."""
        if not url:
            return ""

        try:
            parsed = urlparse(str(url).strip())
            host = (parsed.netloc or parsed.path or "").lower().strip()
            host = host.split("@")[ -1].split(":")[0]
            if host.startswith("www."):
                host = host[4:]
            if not host:
                return ""

            social_hosts = {"twitter.com", "x.com", "linkedin.com", "www.linkedin.com"}
            if host in social_hosts:
                path_parts = [part for part in parsed.path.split("/") if part]
                if path_parts:
                    reserved = {"company", "jobs", "posts", "status", "share", "intent", "home", "search", "hashtag"}
                    slug = path_parts[0].lstrip("@")
                    if slug and slug.lower() not in reserved:
                        slug = re.sub(r"[-_]+", " ", slug).strip()
                        return slug.title() if slug else ""

            parts = [p for p in host.split(".") if p]
            if not parts:
                return ""

            if len(parts) >= 3 and parts[-2] in {"co", "com", "org", "net"} and len(parts[-1]) == 2:
                base = parts[-3]
            elif len(parts) >= 2:
                base = parts[-2]
            else:
                base = parts[0]

            base = re.sub(r"[-_]+", " ", base).strip()
            return base.title() if base else ""
        except Exception:
            return ""
    
    def extract_contacts(self, sample_size: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Extract executive contacts from input CSV
        
        Args:
            sample_size: Optional limit on number of companies to process
        
        Returns:
            List of enriched company records with contact information
        """
        logger.info(f"Reading CSV from: {self.input_csv_path}")

        if callable(self.should_cancel) and self.should_cancel():
            raise ContactExtractionCancelled()
        
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
        
        # Determine source company column from known schema variants.
        company_col = self._resolve_company_column(df)
        if not company_col and 'company_website' in df.columns:
            df['company'] = df['company_website'].fillna('').apply(self._derive_company_from_website)
            company_col = 'company'

        if not company_col:
            logger.error(
                "No company name column found. Expected one of: company, company_name, employer, organization, company_slug"
            )
            return []

        if 'company_website' in df.columns:
            df[company_col] = df[company_col].fillna('').astype('string')
            blank_company = df[company_col].str.strip() == ''
            derived_company = df['company_website'].fillna('').apply(self._derive_company_from_website).astype('string')
            df[company_col] = df[company_col].mask(blank_company, derived_company)
        logger.info("Using company column: %s", company_col)

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
            if callable(self.should_cancel) and self.should_cancel():
                raise ContactExtractionCancelled()
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
            if callable(self.should_cancel) and self.should_cancel():
                raise ContactExtractionCancelled()
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

        source_job_id = (
            record.get("source_job_id")
            or record.get("wantedly_project_id")
            or record.get("linkedin_job_id")
            or record.get("rubyonremote_job_id")
            or ""
        )

        source_platform = record.get("source_platform", "")
        if not source_platform:
            if record.get("wantedly_project_id"):
                source_platform = "wantedly"
            elif record.get("linkedin_job_id"):
                source_platform = "linkedin"
            elif record.get("rubyonremote_job_id"):
                source_platform = "rubyonremote"

        return {
            "source_platform": source_platform,
            "source_job_id": source_job_id,
            "scrape_run_at": record.get("scrape_run_at", ""),
            "url": record.get("url", ""),
            "company": record.get("company", record.get("company_name", "")),
            "company_website": record.get("company_website", ""),
            "title": record.get("title", ""),
            "date": record.get("date", record.get("posted_date", "")),
            "location": record.get("location", record.get("job_location", record.get("location_filter", ""))),
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
