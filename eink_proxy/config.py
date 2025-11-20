import logging
import os
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class ProxySettings:
    source_url: str
    port: int
    contrast: float
    saturation: float
    sharpness_ui: float
    gamma: float
    edge_threshold: int
    mid_l_min: int
    mid_l_max: int
    mid_s_max: int
    mask_blur: int
    timeout: float
    retries: int
    cache_ttl: float
    photo_mode: str
    sky_gradient_threshold: int
    smooth_strength: int
    log_level: str
    ui_palette_threshold: int
    ui_tint_saturation: int
    ui_tint_min_value: int
    texture_density_threshold: int

    @classmethod
    def from_env(cls) -> "ProxySettings":
        return cls(
            source_url=os.getenv(
                "SOURCE_URL",
                "http://192.168.1.199:10000/lovelace-main/einkpanelcolor?viewport=800x480",
            ),
            port=int(os.getenv("PORT", "5500")),
            contrast=float(os.getenv("CONTRAST", "1.25")),
            saturation=float(os.getenv("SATURATION", "1.2")),
            sharpness_ui=float(os.getenv("SHARPNESS_UI", "2.0")),
            gamma=float(os.getenv("GAMMA", "0.95")),
            edge_threshold=int(os.getenv("EDGE_THR", "26")),
            mid_l_min=int(os.getenv("MID_L_MIN", "70")),
            mid_l_max=int(os.getenv("MID_L_MAX", "200")),
            mid_s_max=int(os.getenv("MID_S_MAX", "90")),
            mask_blur=int(os.getenv("MASK_BLUR", "2")),
            timeout=float(os.getenv("SOURCE_TIMEOUT", "10.0")),
            retries=int(os.getenv("SOURCE_RETRIES", "2")),
            cache_ttl=float(os.getenv("CACHE_TTL", "5")),
            photo_mode=os.getenv("PHOTO_MODE", "hybrid").lower(),
            sky_gradient_threshold=int(os.getenv("SKY_GRAD_THR", "14")),
            smooth_strength=int(os.getenv("SMOOTH_STRENGTH", "1")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            ui_palette_threshold=int(os.getenv("UI_PALETTE_THR", "1800")),
            ui_tint_saturation=int(os.getenv("UI_TINT_SAT", "35")),
            ui_tint_min_value=int(os.getenv("UI_TINT_MIN_V", "120")),
            texture_density_threshold=int(os.getenv("TEXTURE_DENSITY_THR", "12")),
        )


SETTINGS = ProxySettings.from_env()


EINK_PALETTE: Tuple[Tuple[int, int, int], ...] = (
    (0, 0, 0),
    (255, 255, 255),
    (255, 0, 0),
    (255, 255, 0),
    (0, 255, 0),
    (0, 0, 255),
    (255, 165, 0),
)


def configure_logging() -> logging.Logger:
    logging.basicConfig(level=SETTINGS.log_level)
    return logging.getLogger("eink-proxy-v2.7")
