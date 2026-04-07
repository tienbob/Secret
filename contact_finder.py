#!/usr/bin/env python
"""
CLI Entry Point for CEO/CTO Contact Finder

Usage:
    python contact_finder.py --input <csv_path> [--output <output_dir>] [--sample <n>] [--verbose]
    
Example:
    python contact_finder.py --input scraper_outputs/wantedly_Ruby_on_Rails_Japan.csv --sample 10
    python contact_finder.py --input scraper_outputs/wantedly_Ruby_on_Rails_Japan.csv --output results
"""

import argparse
import logging
import sys
from pathlib import Path

from contact_extractor import ContactExtractor


def setup_logging(verbose: bool = False):
    """Configure logging based on verbosity flag"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


def main():
    parser = argparse.ArgumentParser(
        description="Find CEO/CTO contact information for companies from job scraper outputs using Gemini or Ollama",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Configuration: Set LLM_MODEL_TYPE in .env to 'gemini' or 'ollama'

Examples with Gemini (cloud):
  # Set .env: LLM_MODEL_TYPE=gemini, GOOGLE_API_KEY=...
  %(prog)s --input scraper_outputs/wantedly_Ruby_on_Rails_Japan.csv --sample 5
  
Examples with Ollama (local):
  # Set .env: LLM_MODEL_TYPE=ollama, OLLAMA_MODEL=mistral
  # Make sure: ollama serve (running in another terminal)
  %(prog)s --input scraper_outputs/wantedly_Ruby_on_Rails_Japan.csv --sample 5 --verbose
  
Full batch processing:
  %(prog)s --input scraper_outputs/wantedly_Ruby_on_Rails_Japan.csv
  
Custom output:
  %(prog)s --input scraper_outputs/wantedly_Ruby_on_Rails_Japan.csv --output ./results
        """
    )
    
    parser.add_argument(
        "-i", "--input",
        required=True,
        help="Path to input CSV file from scraper output",
        metavar="CSV_PATH"
    )
    
    parser.add_argument(
        "-o", "--output",
        default="scraper_outputs",
        help="Output directory for enriched CSV (default: scraper_outputs)",
        metavar="OUTPUT_DIR"
    )
    
    parser.add_argument(
        "-s", "--sample",
        type=int,
        help="Limit processing to first N companies (useful for testing)",
        metavar="N"
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging output"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(args.verbose)
    
    logger = logging.getLogger(__name__)
    
    # Validate input file exists
    if not Path(args.input).exists():
        logger.error(f"Input file not found: {args.input}")
        sys.exit(1)
    
    try:
        logger.info("=" * 70)
        logger.info("CEO/CTO Contact Finder")
        logger.info("=" * 70)
        logger.info(f"Input CSV: {args.input}")
        logger.info(f"Output Dir: {args.output}")
        if args.sample:
            logger.info(f"Sample Size: {args.sample} companies")
        logger.info("-" * 70)
        
        # Create extractor
        extractor = ContactExtractor(args.input, args.output)
        
        # Extract contacts
        enriched_records = extractor.extract_contacts(sample_size=args.sample)
        
        if enriched_records:
            # Save enriched CSV
            output_path = extractor.save_enriched_csv(enriched_records)
            
            # Save and display stats
            stats = extractor.save_stats()
            
            logger.info("-" * 70)
            logger.info("✓ Processing completed successfully!")
            logger.info(f"✓ Processed {len(enriched_records)} records")
            logger.info(f"✓ Output: {output_path}")
            logger.info("=" * 70)
            
            return 0
        else:
            logger.warning("No records were enriched")
            return 1
    
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=args.verbose)
        return 1


if __name__ == "__main__":
    sys.exit(main())
