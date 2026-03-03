"""Media integration adapters."""

from .space_scraper import scrape_space_html
from .yt_dlp_resolver import YtDlpResolver

__all__ = ["YtDlpResolver", "scrape_space_html"]
