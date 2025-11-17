#!/usr/bin/env python3
"""
Upload Project Gutenberg books to InvenioRDM.
Reads metadata and text files from the Gutenberg download and creates InvenioRDM records.
"""

import csv
import json
import os
import requests
import time
from pathlib import Path
from typing import Dict, List, Optional
import urllib3

try:
    import pycountry
except ImportError:
    pycountry = None

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class InvenioUploader:
    """Upload books to InvenioRDM via REST API."""

    def __init__(
        self,
        base_url: str = "https://127.0.0.1:5000",
        token_file: str = ".api_token",
        data_dir: str = "gutenberg_data"
    ):
        self.base_url = base_url.rstrip('/')
        self.api_url = f"{self.base_url}/api"
        self.data_dir = Path(data_dir)

        # Load API token
        token_path = Path(token_file)
        if not token_path.exists():
            raise FileNotFoundError(
                f"API token not found at {token_file}. "
                "Run scripts/gutenberg/setup_user.sh first."
            )

        self.token = token_path.read_text().strip()
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        # Load publication years and Wikipedia URLs mapping
        self.publication_years, self.wikipedia_urls = self._load_publication_data()

    def _load_publication_data(self) -> tuple:
        """
        Load publication years and Wikipedia URLs from CSV file.

        Returns:
            Tuple of (publication_years dict, wikipedia_urls dict)
        """
        pub_years_file = self.data_dir / "gutenberg_publication_years.csv"

        if not pub_years_file.exists():
            print(f"Warning: Publication years file not found at {pub_years_file}")
            print("  Using fallback dates for all books.")
            return {}, {}

        pub_years = {}
        wiki_urls = {}
        try:
            with open(pub_years_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        gutenberg_id = int(row['gutenberg_id'])
                        pub_year = int(row['publication_year'])
                        pub_years[gutenberg_id] = pub_year

                        # Store Wikipedia URL if present
                        wiki_url = row.get('wikipedia_url', '').strip()
                        if wiki_url:
                            wiki_urls[gutenberg_id] = wiki_url
                    except (ValueError, KeyError):
                        # Skip rows with invalid data
                        continue

            print(f"Loaded {len(pub_years)} publication years and {len(wiki_urls)} Wikipedia URLs from {pub_years_file.name}")
            return pub_years, wiki_urls

        except Exception as e:
            print(f"Warning: Failed to load publication data: {e}")
            print("  Using fallback dates for all books.")
            return {}, {}

    def create_metadata(self, book_meta: Dict) -> Dict:
        """
        Convert Gutenberg metadata to InvenioRDM format.

        Args:
            book_meta: Gutenberg book metadata from Gutendex

        Returns:
            InvenioRDM-formatted metadata dictionary
        """
        # Extract authors
        creators = []
        for author in book_meta.get('authors', []):
            author_name = author.get('name', 'Unknown Author')
            # Parse "Last, First" format
            if ',' in author_name:
                parts = author_name.split(',', 1)
                family_name = parts[0].strip()
                given_name = parts[1].strip() if len(parts) > 1 else ""
            else:
                # Use full name as family name if no comma
                family_name = author_name
                given_name = ""

            creator = {
                "person_or_org": {
                    "type": "personal",
                    "name": author_name,
                }
            }

            if given_name:
                creator["person_or_org"]["given_name"] = given_name
            if family_name:
                creator["person_or_org"]["family_name"] = family_name

            creators.append(creator)

        # If no authors, use "Unknown"
        if not creators:
            creators = [{
                "person_or_org": {
                    "type": "personal",
                    "name": "Unknown Author",
                    "family_name": "Unknown",
                }
            }]

        # Extract subjects
        subjects = []
        for subject in book_meta.get('subjects', []):
            subjects.append({"subject": subject})

        # Use first bookshelf as additional subject if available
        if book_meta.get('bookshelves'):
            for shelf in book_meta['bookshelves'][:3]:  # Limit to 3
                subjects.append({"subject": shelf})

        # Build description from summary if available
        description = ""
        if book_meta.get('summaries'):
            description = book_meta['summaries'][0]

        # Determine publication date from dataset or use fallback
        book_id = book_meta.get('id')
        if book_id and book_id in self.publication_years:
            pub_year = self.publication_years[book_id]
            pub_date = str(pub_year)  # InvenioRDM accepts just year
        else:
            # Fallback for books without known publication date
            pub_date = "1900"

        # Create InvenioRDM metadata
        metadata = {
            "resource_type": {"id": "publication-book"},
            "title": book_meta.get('title', f"Book {book_meta.get('id')}"),
            "creators": creators,
            "publication_date": pub_date,
        }

        # Add languages (convert ISO 639-1 to ISO 639-3)
        languages_list = book_meta.get('languages', [])
        if languages_list:
            converted_langs = []
            for lang_code in languages_list:
                # Convert ISO 639-1 (2-letter) to ISO 639-3 (3-letter)
                if pycountry and len(lang_code) == 2:
                    try:
                        lang = pycountry.languages.get(alpha_2=lang_code)
                        if lang:
                            converted_langs.append({"id": lang.alpha_3})
                        else:
                            # Fallback if not found
                            converted_langs.append({"id": lang_code})
                    except (AttributeError, KeyError):
                        converted_langs.append({"id": lang_code})
                else:
                    # Already 3-letter or pycountry not available
                    converted_langs.append({"id": lang_code})

            if converted_langs:
                metadata["languages"] = converted_langs

        # Add optional fields
        if description:
            metadata["description"] = description

        if subjects:
            metadata["subjects"] = subjects

        # Add alternate identifiers
        identifiers = []
        if book_id:
            identifiers.append({
                "identifier": str(book_id),
                "scheme": "other"  # Project Gutenberg ID
            })
        if identifiers:
            metadata["identifiers"] = identifiers

        # Add contributors (editors and translators)
        contributors = []
        for editor in book_meta.get('editors', []):
            editor_name = editor.get('name', 'Unknown Editor')
            # Parse "Last, First" format
            if ',' in editor_name:
                parts = editor_name.split(',', 1)
                family_name = parts[0].strip()
                given_name = parts[1].strip() if len(parts) > 1 else ""
            else:
                # Use full name as family name if no comma
                family_name = editor_name
                given_name = ""

            contributor = {
                "person_or_org": {
                    "type": "personal",
                    "name": editor_name,
                },
                "role": {"id": "editor"}
            }

            if given_name:
                contributor["person_or_org"]["given_name"] = given_name
            if family_name:
                contributor["person_or_org"]["family_name"] = family_name

            contributors.append(contributor)

        for translator in book_meta.get('translators', []):
            translator_name = translator.get('name', 'Unknown Translator')
            # Parse "Last, First" format
            if ',' in translator_name:
                parts = translator_name.split(',', 1)
                family_name = parts[0].strip()
                given_name = parts[1].strip() if len(parts) > 1 else ""
            else:
                # Use full name as family name if no comma
                family_name = translator_name
                given_name = ""

            contributor = {
                "person_or_org": {
                    "type": "personal",
                    "name": translator_name,
                },
                "role": {"id": "other"}  # No "translator" role in vocabulary
            }

            if given_name:
                contributor["person_or_org"]["given_name"] = given_name
            if family_name:
                contributor["person_or_org"]["family_name"] = family_name

            contributors.append(contributor)

        if contributors:
            metadata["contributors"] = contributors

        # Add format
        metadata["formats"] = ["text/plain"]

        # Add publisher
        metadata["publisher"] = "Project Gutenberg"

        # Add rights information
        metadata["rights"] = [{
            "title": {"en": "Public Domain"},
            "description": {
                "en": "This work is in the public domain in the United States."
            },
        }]

        # Add additional description with Project Gutenberg ID
        metadata["additional_descriptions"] = [{
            "description": f"Project Gutenberg eBook #{book_meta.get('id')}. "
                         f"Downloaded from https://www.gutenberg.org/ebooks/{book_meta.get('id')}",
            "type": {"id": "other"}
        }]

        # Add Wikipedia URL as a related identifier if available
        if book_id and book_id in self.wikipedia_urls:
            wiki_url = self.wikipedia_urls[book_id]
            metadata["related_identifiers"] = [{
                "identifier": wiki_url,
                "scheme": "url",
                "relation_type": {"id": "describes"},
                "resource_type": {"id": "other"}
            }]

        return metadata

    def create_draft(self, metadata: Dict) -> Optional[Dict]:
        """
        Create a draft record in InvenioRDM.

        Args:
            metadata: InvenioRDM-formatted metadata

        Returns:
            Draft record response or None if failed
        """
        payload = {
            "access": {
                "record": "public",
                "files": "public"
            },
            "files": {
                "enabled": True
            },
            "metadata": metadata
        }

        try:
            response = requests.post(
                f"{self.api_url}/records",
                headers=self.headers,
                json=payload,
                verify=False  # Self-signed cert
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"  Error creating draft: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"  Response: {e.response.text}")
            return None

    def upload_file(self, record_id: str, filename: str, file_path: Path) -> bool:
        """
        Upload a file to a draft record.

        Args:
            record_id: Draft record ID
            filename: Name for the file
            file_path: Path to the file to upload

        Returns:
            True if successful, False otherwise
        """
        try:
            # Step 1: Initiate file upload
            init_payload = [{"key": filename}]
            response = requests.post(
                f"{self.api_url}/records/{record_id}/draft/files",
                headers=self.headers,
                json=init_payload,
                verify=False
            )
            response.raise_for_status()

            # Step 2: Upload file content
            with open(file_path, 'rb') as f:
                content_headers = {
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/octet-stream",
                }
                response = requests.put(
                    f"{self.api_url}/records/{record_id}/draft/files/{filename}/content",
                    headers=content_headers,
                    data=f,
                    verify=False
                )
                response.raise_for_status()

            # Step 3: Commit the file
            response = requests.post(
                f"{self.api_url}/records/{record_id}/draft/files/{filename}/commit",
                headers=self.headers,
                verify=False
            )
            response.raise_for_status()

            return True

        except Exception as e:
            print(f"  Error uploading file: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"  Response: {e.response.text}")
            return False

    def publish_draft(self, record_id: str) -> Optional[Dict]:
        """
        Publish a draft record.

        Args:
            record_id: Draft record ID

        Returns:
            Published record response or None if failed
        """
        try:
            response = requests.post(
                f"{self.api_url}/records/{record_id}/draft/actions/publish",
                headers=self.headers,
                verify=False
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"  Error publishing draft: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"  Response: {e.response.text}")
            return None

    def upload_book(self, book_metadata_file: Path) -> bool:
        """
        Upload a single book to InvenioRDM.

        Args:
            book_metadata_file: Path to the book's metadata JSON file

        Returns:
            True if successful, False otherwise
        """
        # Load metadata
        with open(book_metadata_file, 'r', encoding='utf-8') as f:
            gutenberg_meta = json.load(f)

        book_id = gutenberg_meta['id']
        title = gutenberg_meta.get('title', f'Book {book_id}')

        print(f"\nUploading: {title} (ID: {book_id})")

        # Find the corresponding text file
        base_name = book_metadata_file.stem  # Remove .json
        text_file = self.data_dir / "books" / f"{base_name}.txt"

        if not text_file.exists():
            print(f"  ✗ Text file not found: {text_file}")
            return False

        # Create metadata
        print(f"  Creating draft record...")
        invenio_metadata = self.create_metadata(gutenberg_meta)
        draft = self.create_draft(invenio_metadata)

        if not draft:
            print(f"  ✗ Failed to create draft")
            return False

        record_id = draft['id']
        print(f"  ✓ Draft created (ID: {record_id})")

        # Upload file
        print(f"  Uploading text file...")
        if not self.upload_file(record_id, f"{base_name}.txt", text_file):
            print(f"  ✗ Failed to upload file")
            return False

        print(f"  ✓ File uploaded")

        # Publish
        print(f"  Publishing record...")
        published = self.publish_draft(record_id)

        if not published:
            print(f"  ✗ Failed to publish")
            return False

        record_url = f"{self.base_url}/records/{published['id']}"
        print(f"  ✓ Published: {record_url}")

        return True

    def upload_all(self, limit: Optional[int] = None):
        """
        Upload all books from the metadata directory.

        Args:
            limit: Optional limit on number of books to upload
        """
        metadata_dir = self.data_dir / "metadata"

        if not metadata_dir.exists():
            print(f"Metadata directory not found: {metadata_dir}")
            return

        # Get all metadata files
        metadata_files = sorted(metadata_dir.glob("*.json"))

        if limit:
            metadata_files = metadata_files[:limit]

        print(f"{'='*60}")
        print(f"Uploading {len(metadata_files)} books to InvenioRDM")
        print(f"API: {self.api_url}")
        print(f"{'='*60}")

        successful = 0
        failed = []

        for i, metadata_file in enumerate(metadata_files, 1):
            print(f"\n[{i}/{len(metadata_files)}]", end=" ")

            if self.upload_book(metadata_file):
                successful += 1
            else:
                failed.append(metadata_file.stem)

            # Rate limiting - be nice to the server
            time.sleep(1)

        # Summary
        print(f"\n{'='*60}")
        print(f"Upload Summary:")
        print(f"  Successful: {successful}/{len(metadata_files)}")
        print(f"  Failed: {len(failed)}")

        if failed:
            print(f"\nFailed uploads:")
            for name in failed:
                print(f"  - {name}")

        print(f"{'='*60}")

    def get_existing_records(self, page_size: int = 100):
        """
        Fetch existing records from the repository.

        Args:
            page_size: Number of records per page

        Yields:
            Record dictionaries (only Project Gutenberg books)
        """
        page = 1
        while True:
            try:
                url = f"{self.api_url}/records"
                params = {
                    "size": page_size,
                    "page": page,
                }

                response = requests.get(
                    url,
                    params=params,
                    headers={"Accept": "application/json"},
                    verify=False
                )
                response.raise_for_status()

                data = response.json()
                hits = data.get('hits', {}).get('hits', [])

                if not hits:
                    break

                for record in hits:
                    # Only yield Project Gutenberg records
                    publisher = record.get('metadata', {}).get('publisher', '')
                    if publisher == 'Project Gutenberg':
                        yield record

                page += 1
                time.sleep(0.5)  # Rate limiting

            except Exception as e:
                print(f"Error fetching records: {e}")
                break

    def extract_gutenberg_id(self, record: Dict) -> Optional[int]:
        """
        Extract Gutenberg ID from record metadata.

        Args:
            record: InvenioRDM record

        Returns:
            Gutenberg ID or None
        """
        # Check additional_descriptions for Gutenberg ID
        metadata = record.get('metadata', {})
        for desc in metadata.get('additional_descriptions', []):
            desc_text = desc.get('description', '')
            if 'Project Gutenberg eBook #' in desc_text:
                try:
                    # Extract ID from text like "Project Gutenberg eBook #84."
                    id_str = desc_text.split('#')[1].split('.')[0]
                    return int(id_str)
                except (IndexError, ValueError):
                    continue

        return None

    def create_new_version(self, record_id: str) -> Optional[Dict]:
        """
        Create a new version draft of an existing record.

        Args:
            record_id: Record ID

        Returns:
            New version draft or None if failed
        """
        try:
            response = requests.post(
                f"{self.api_url}/records/{record_id}/versions",
                headers=self.headers,
                verify=False
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"  Error creating new version: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"  Response: {e.response.text}")
            return None

    def import_files_from_previous_version(self, draft_id: str) -> bool:
        """
        Import files from the previous version.

        Args:
            draft_id: Draft ID

        Returns:
            True if successful
        """
        try:
            response = requests.post(
                f"{self.api_url}/records/{draft_id}/draft/actions/files-import",
                headers=self.headers,
                verify=False
            )
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"  Error importing files: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"  Response: {e.response.text}")
            return False

    def update_draft_metadata(self, draft_id: str, updated_metadata: Dict) -> bool:
        """
        Update a draft's metadata.

        Args:
            draft_id: Draft ID
            updated_metadata: New metadata

        Returns:
            True if successful
        """
        try:
            payload = {"metadata": updated_metadata}

            response = requests.put(
                f"{self.api_url}/records/{draft_id}/draft",
                headers=self.headers,
                json=payload,
                verify=False
            )
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"  Error updating draft: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"  Response: {e.response.text}")
            return False

    def update_record(self, record: Dict) -> bool:
        """
        Update a single record with enhanced metadata.

        Args:
            record: Existing record

        Returns:
            True if successful
        """
        record_id = record.get('id')
        metadata = record.get('metadata', {})
        title = metadata.get('title', 'Unknown')

        print(f"\nUpdating: {title}")
        print(f"  Record ID: {record_id}")

        # Extract Gutenberg ID
        gutenberg_id = self.extract_gutenberg_id(record)
        if not gutenberg_id:
            print(f"  ✗ Could not extract Gutenberg ID, skipping")
            return False

        print(f"  Gutenberg ID: {gutenberg_id}")

        # Load corresponding Gutenberg metadata file
        metadata_dir = self.data_dir / "metadata"
        metadata_files = list(metadata_dir.glob(f"{gutenberg_id}_*.json"))

        if not metadata_files:
            print(f"  ✗ Gutenberg metadata file not found")
            return False

        with open(metadata_files[0], 'r', encoding='utf-8') as f:
            gutenberg_meta = json.load(f)

        # Create enhanced metadata
        enhanced_metadata = self.create_metadata(gutenberg_meta)

        # Create new version
        print(f"  Creating new version...")
        new_draft = self.create_new_version(record_id)
        if not new_draft:
            print(f"  ✗ Failed to create new version")
            return False

        draft_id = new_draft.get('id')
        print(f"  ✓ New version draft created: {draft_id}")

        # Import files from previous version
        print(f"  Importing files from previous version...")
        if not self.import_files_from_previous_version(draft_id):
            print(f"  ✗ Failed to import files")
            return False

        print(f"  ✓ Files imported")

        # Update metadata
        print(f"  Updating metadata...")
        if not self.update_draft_metadata(draft_id, enhanced_metadata):
            print(f"  ✗ Failed to update metadata")
            return False

        print(f"  ✓ Metadata updated")

        # Publish
        print(f"  Publishing...")
        published = self.publish_draft(draft_id)
        if not published:
            print(f"  ✗ Failed to publish")
            return False

        print(f"  ✓ Published successfully")
        return True

    def update_all(self, limit: Optional[int] = None):
        """
        Update all Gutenberg records with enhanced metadata.

        Args:
            limit: Optional limit on number of records to update
        """
        print(f"{'='*60}")
        print(f"Updating Project Gutenberg records with enhanced metadata")
        print(f"API: {self.api_url}")
        print(f"{'='*60}")

        successful = 0
        failed = []
        count = 0

        for record in self.get_existing_records():
            count += 1
            if limit and count > limit:
                break

            if self.update_record(record):
                successful += 1
            else:
                record_id = record.get('id')
                title = record.get('metadata', {}).get('title', 'Unknown')
                failed.append((record_id, title))

            # Rate limiting
            time.sleep(1)

        # Summary
        print(f"\n{'='*60}")
        print(f"Update Summary:")
        print(f"  Successful: {successful}")
        print(f"  Failed: {len(failed)}")

        if failed:
            print(f"\nFailed updates:")
            for record_id, title in failed:
                print(f"  - {record_id}: {title}")

        print(f"{'='*60}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Upload or update Project Gutenberg books in InvenioRDM'
    )
    parser.add_argument(
        '-d', '--data-dir',
        type=str,
        default='gutenberg_data',
        help='Directory containing downloaded books (default: gutenberg_data)'
    )
    parser.add_argument(
        '-u', '--url',
        type=str,
        default='https://127.0.0.1:5000',
        help='InvenioRDM base URL (default: https://127.0.0.1:5000)'
    )
    parser.add_argument(
        '-t', '--token-file',
        type=str,
        default='.api_token',
        help='API token file (default: .api_token)'
    )
    parser.add_argument(
        '-n', '--limit',
        type=int,
        help='Limit number of books to process (default: all)'
    )
    parser.add_argument(
        '--update',
        action='store_true',
        help='Update existing records with enhanced metadata instead of uploading new books'
    )

    args = parser.parse_args()

    uploader = InvenioUploader(
        base_url=args.url,
        token_file=args.token_file,
        data_dir=args.data_dir
    )

    if args.update:
        uploader.update_all(limit=args.limit)
    else:
        uploader.upload_all(limit=args.limit)


if __name__ == '__main__':
    main()
