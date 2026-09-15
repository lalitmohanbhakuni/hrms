# core/validators.py
"""
Custom file validators for uploads.
Blocks dangerous extensions and enforces size caps.
"""
import os
from django.core.exceptions import ValidationError


def validate_image_file(file):
    """Validate uploaded image: extension + size + MIME."""
    ext = os.path.splitext(file.name)[1].lower().lstrip('.')

    # Extension whitelist
    allowed = ['jpg', 'jpeg', 'png', 'gif', 'webp']
    if ext not in allowed:
        raise ValidationError(
            f'Unsupported image format ".{ext}". Allowed: {", ".join(allowed)}.'
        )

    # Size cap
    max_bytes = 2 * 1024 * 1024   # 2 MB
    if file.size > max_bytes:
        raise ValidationError(
            f'Image too large ({file.size / 1024 / 1024:.1f} MB). Max: 2 MB.'
        )

    # MIME sniffing
    content_type = getattr(file, 'content_type', '').lower()
    allowed_mimes = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
    if content_type and content_type not in allowed_mimes:
        raise ValidationError(
            f'Invalid image type: {content_type}.'
        )

    return file


def validate_attachment_file(file):
    """Validate uploaded attachment: extension + size."""
    ext = os.path.splitext(file.name)[1].lower().lstrip('.')

    allowed = ['pdf', 'jpg', 'jpeg', 'png', 'doc', 'docx']
    if ext not in allowed:
        raise ValidationError(
            f'Unsupported file type ".{ext}". Allowed: {", ".join(allowed)}.'
        )

    max_bytes = 5 * 1024 * 1024   # 5 MB
    if file.size > max_bytes:
        raise ValidationError(
            f'File too large ({file.size / 1024 / 1024:.1f} MB). Max: 5 MB.'
        )

    # Reject double-extension attacks (e.g., photo.jpg.php)
    parts = file.name.split('.')
    if len(parts) > 2:
        # Allow only common two-part extensions like .tar.gz
        if parts[-1].lower() not in allowed:
            raise ValidationError('Invalid file extension.')

    return file