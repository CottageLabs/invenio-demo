#!/usr/bin/env python3
"""
Download Project Gutenberg books using the Gutendex API.
Downloads 100 English books with full metadata and text content.
"""

import json
import os
import re
import requests
import time
from pathlib import Path
from typing import Dict, List, Optional


class GutenbergDownloader:
    """Download books from Project Gutenberg using Gutendex API."""

    GUTENDEX_API = "https://gutendex.com/books"
    GUTENBERG_TEXT_URL = "https://www.gutenberg.org/files/{id}/{id}-0.txt"

    def __init__(self, output_dir: str = "gutenberg_data"):
        self.output_dir = Path(output_dir)
        self.books_dir = self.output_dir / "books"
        self.metadata_dir = self.output_dir / "metadata"

        # Create directories
        self.books_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)

    def fetch_metadata(self, num_books: int = 100, language: str = "en") -> List[Dict]:
        """
        Fetch metadata for books from Gutendex API.

        Args:
            num_books: Number of books to fetch
            language: Language code (default: "en" for English)

        Returns:
            List of book metadata dictionaries
        """
        print(f"Fetching metadata for {num_books} {language} books from Gutendex API...")

        books = []
        url = f"{self.GUTENDEX_API}?languages={language}"

        while len(books) < num_books and url:
            try:
                response = requests.get(url, timeout=30)
                response.raise_for_status()

                data = response.json()
                books.extend(data['results'])
                url = data.get('next')

                print(f"  Fetched {len(books)} books so far...")
                time.sleep(1)  # Be polite to the API

            except Exception as e:
                print(f"Error fetching metadata: {e}")
                break

        # Trim to exact number requested
        books = books[:num_books]
        print(f"Successfully fetched metadata for {len(books)} books")

        return books

    def strip_gutenberg_headers(self, text: str) -> str:
        """
        Remove Project Gutenberg legal headers and footers.

        Args:
            text: Raw book text

        Returns:
            Cleaned book text
        """
        # Find start of actual content
        start_markers = [
            r'\*\*\* START OF THIS PROJECT GUTENBERG EBOOK .+ \*\*\*',
            r'\*\*\*START OF THE PROJECT GUTENBERG EBOOK .+ \*\*\*',
            r'START OF THIS PROJECT GUTENBERG EBOOK',
        ]

        start_pos = 0
        for marker in start_markers:
            match = re.search(marker, text, re.IGNORECASE)
            if match:
                start_pos = match.end()
                break

        # Find end of actual content
        end_markers = [
            r'\*\*\* END OF THIS PROJECT GUTENBERG EBOOK .+ \*\*\*',
            r'\*\*\*END OF THE PROJECT GUTENBERG EBOOK .+ \*\*\*',
            r'END OF THIS PROJECT GUTENBERG EBOOK',
        ]

        end_pos = len(text)
        for marker in end_markers:
            match = re.search(marker, text, re.IGNORECASE)
            if match:
                end_pos = match.start()
                break

        # Extract content and clean up
        content = text[start_pos:end_pos].strip()
        return content

    def download_book_text(self, book_id: int) -> Optional[str]:
        """
        Download the plain text content of a book.

        Args:
            book_id: Project Gutenberg book ID

        Returns:
            Book text content or None if download fails
        """
        url = self.GUTENBERG_TEXT_URL.format(id=book_id)

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            # Try to decode with UTF-8, fall back to latin-1
            try:
                text = response.content.decode('utf-8')
            except UnicodeDecodeError:
                text = response.content.decode('latin-1')

            # Strip headers and footers
            clean_text = self.strip_gutenberg_headers(text)

            return clean_text

        except Exception as e:
            print(f"  Error downloading book {book_id}: {e}")
            return None

    def sanitize_filename(self, text: str, max_length: int = 100) -> str:
        """Create a safe filename from text."""
        # Remove or replace invalid characters
        text = re.sub(r'[<>:"/\\|?*]', '', text)
        text = re.sub(r'\s+', '_', text)
        text = text.strip('._')

        # Limit length
        if len(text) > max_length:
            text = text[:max_length].rsplit('_', 1)[0]

        return text

    def save_book(self, book_metadata: Dict, book_text: str) -> bool:
        """
        Save book text and metadata to files.

        Args:
            book_metadata: Book metadata dictionary
            book_text: Book text content

        Returns:
            True if save successful, False otherwise
        """
        book_id = book_metadata['id']
        title = book_metadata.get('title', f'Book_{book_id}')

        # Create safe filename
        safe_title = self.sanitize_filename(title)
        filename_base = f"{book_id}_{safe_title}"

        # Save text
        text_path = self.books_dir / f"{filename_base}.txt"
        try:
            with open(text_path, 'w', encoding='utf-8') as f:
                f.write(book_text)
        except Exception as e:
            print(f"  Error saving text for {book_id}: {e}")
            return False

        # Save metadata
        metadata_path = self.metadata_dir / f"{filename_base}.json"
        try:
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(book_metadata, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"  Error saving metadata for {book_id}: {e}")
            return False

        return True

    def download_all(self, num_books: int = 100, language: str = "en"):
        """
        Download books with metadata.

        Args:
            num_books: Number of books to download
            language: Language code
        """
        # Fetch metadata
        books_metadata = self.fetch_metadata(num_books, language)

        if not books_metadata:
            print("No books found!")
            return

        # Download books
        print(f"\nDownloading {len(books_metadata)} books...")
        successful = 0
        failed = []

        for i, book_meta in enumerate(books_metadata, 1):
            book_id = book_meta['id']
            title = book_meta.get('title', 'Unknown')

            print(f"\n[{i}/{len(books_metadata)}] Downloading: {title} (ID: {book_id})")

            # Download text
            book_text = self.download_book_text(book_id)

            if book_text:
                # Save book and metadata
                if self.save_book(book_meta, book_text):
                    successful += 1
                    print(f"  ✓ Saved successfully")
                else:
                    failed.append((book_id, title, "Save failed"))
            else:
                failed.append((book_id, title, "Download failed"))

            # Rate limiting - be respectful to the server
            time.sleep(2)

        # Summary
        print(f"\n{'='*60}")
        print(f"Download Summary:")
        print(f"  Successful: {successful}/{len(books_metadata)}")
        print(f"  Failed: {len(failed)}")

        if failed:
            print(f"\nFailed downloads:")
            for book_id, title, reason in failed:
                print(f"  - {book_id}: {title} ({reason})")

        # Save master metadata file
        master_metadata_path = self.output_dir / "all_books_metadata.json"
        with open(master_metadata_path, 'w', encoding='utf-8') as f:
            json.dump(books_metadata, f, indent=2, ensure_ascii=False)

        print(f"\nAll metadata saved to: {master_metadata_path}")
        print(f"Books saved to: {self.books_dir}")
        print(f"Individual metadata saved to: {self.metadata_dir}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Download Project Gutenberg books')
    parser.add_argument(
        '-n', '--num-books',
        type=int,
        default=100,
        help='Number of books to download (default: 100)'
    )
    parser.add_argument(
        '-l', '--language',
        type=str,
        default='en',
        help='Language code (default: en for English)'
    )
    parser.add_argument(
        '-o', '--output-dir',
        type=str,
        default='gutenberg_data',
        help='Output directory (default: gutenberg_data)'
    )

    args = parser.parse_args()

    downloader = GutenbergDownloader(output_dir=args.output_dir)
    downloader.download_all(num_books=args.num_books, language=args.language)


if __name__ == '__main__':
    main()
