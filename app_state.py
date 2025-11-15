from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AssetPaths:
    """Represents user-selected files and folders used across the app."""

    input_file: str = ""
    output_dir: str = "qr_results"
    logo_file: str = ""


@dataclass
class TextSettings:
    """All text customization knobs that feed template rendering."""

    title: str = "VPN Configuration"
    subtitle: str = "Scan to Connect"
    name_prefix: str = "VPN"
    title_font_size: int = 32
    subtitle_font_size: int = 18
    name_font_size: int = 24
    text_color: str = "#FFFFFF"

@dataclass
class GenerationOptions:
    """Options that influence QR generation/export."""

    qr_scale: int = 15
    output_dpi: int = 400
    output_quality: int = 98
    output_format: str = "PNG"
    create_zip: bool = False
    create_pdf: bool = False
