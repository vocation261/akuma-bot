"""
Security validation module for user inputs.
Prevents SQL injection, command injection, path traversal, and other attacks.
"""

from __future__ import annotations

import re
from typing import Any

from akuma_bot.infrastructure.runtime.text_utils import is_x_space_url


class ValidationError(Exception):
    """Raised when input validation fails."""
    pass


class InputValidator:
    """Validates user input to prevent security vulnerabilities."""
    
    # Valid event types for audit log
    VALID_EVENT_TYPES = {
        "bookmark_add", "bookmark_delete", "bookmark_clear",
        "alert_add", "alert_remove", "alert_interval",
        "transcript", "play_audio", "stop_playback",
        "pause_resume", "seek_audio", "history_query",
        "panel_upsert", "health_check", "participants_query"
    }
    
    @staticmethod
    def validate_url(url: str) -> str:
        """
        Validate X Space URL format.
        Prevents URL injection and command injection via URL parameters.
        """
        text = str(url or "").strip()
        
        if not text:
            raise ValidationError("URL cannot be empty")
        
        if len(text) > 2048:
            raise ValidationError("URL is too long (max 2048 characters)")
        
        # Must be https protocol
        if not re.match(r"^https://", text, re.IGNORECASE):
            raise ValidationError("Must be https:// URL")
        
        # Must match X Space URL pattern
        if not is_x_space_url(text):
            raise ValidationError("Invalid X Space URL format")
        
        return text.strip()
    
    @staticmethod
    def validate_string(value: str, field_name: str, max_length: int = 500, allow_empty: bool = True) -> str:
        """
        Validate and sanitize a string input.
        """
        text = str(value or "").strip()
        
        # Check length
        if len(text) > max_length:
            raise ValidationError(f"{field_name} exceeds maximum length ({max_length} chars)")
        
        if not allow_empty and not text:
            raise ValidationError(f"{field_name} cannot be empty")
        
        return text
    
    @staticmethod
    def validate_integer(value: Any, field_name: str, min_val: int | None = None, max_val: int | None = None) -> int:
        """
        Validate and convert an integer input.
        """
        try:
            num = int(value)
        except (ValueError, TypeError):
            raise ValidationError(f"{field_name} must be an integer")
        
        if min_val is not None and num < min_val:
            raise ValidationError(f"{field_name} must be >= {min_val}")
        
        if max_val is not None and num > max_val:
            raise ValidationError(f"{field_name} must be <= {max_val}")
        
        return num
    
    @staticmethod
    def validate_handle(handle: str) -> str:
        """
        Validate X/Twitter handle or numeric ID.
        Prevents SQL injection and invalid handles.
        """
        text = str(handle or "").strip().lstrip("@")
        
        if not text:
            raise ValidationError("Handle cannot be empty")
        
        if len(text) > 200:
            raise ValidationError("Handle is too long")
        
        # If numeric, must be digit string
        if text.isdigit():
            return text
        
        # If alphanumeric, allow basic handles
        if not re.match(r"^[a-zA-Z0-9_]+$", text):
            raise ValidationError("Invalid handle format (only alphanumeric and underscore allowed)")
        
        return text
    
    @staticmethod
    def validate_event_type(event_type: str) -> str:
        """
        Validate audit log event type.
        Prevents injection via event type field.
        """
        text = str(event_type or "").strip().lower()
        
        if text and text not in InputValidator.VALID_EVENT_TYPES:
            raise ValidationError(f"Invalid event type: {text}")
        
        return text
    
    @staticmethod
    def validate_alert_interval(seconds: int) -> int:
        """
        Validate alert polling interval.
        """
        num = InputValidator.validate_integer(seconds, "Interval", min_val=10, max_val=3600)
        return num
    
    @staticmethod
    def validate_bookmark_title(title: str) -> str:
        """
        Validate bookmark title.
        """
        return InputValidator.validate_string(title, "Title", max_length=250, allow_empty=True)
    
    @staticmethod
    def validate_bookmark_id(bookmark_id: int) -> int:
        """
        Validate bookmark ID.
        """
        return InputValidator.validate_integer(bookmark_id, "Bookmark ID", min_val=1)
    
    @staticmethod
    def validate_limit(limit: int, max_limit: int = 100) -> int:
        """
        Validate pagination limit.
        """
        return InputValidator.validate_integer(limit, "Limit", min_val=1, max_val=max_limit)
    
    @staticmethod
    def validate_action(action: str, valid_actions: set[str] | None = None) -> str:
        """
        Validate action parameter.
        """
        text = str(action or "").strip().lower()
        
        default_actions = {"list", "delete", "clear", "add", "remove"}
        allowed = valid_actions or default_actions
        
        if text not in allowed:
            raise ValidationError(f"Invalid action: {text}")
        
        return text
