"""Configuration loading, validation, and TOML serialization.

The daemon keeps working with no config file at all: defaults are used and a
commented config is created on first launch. Values are read from, in order:

1. command-line overrides (``--crop``, ``--retries``, ...)
2. the TOML config file (``--config PATH`` or the XDG default)
3. the defaults in :class:`Config`
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:  # pragma: no cover
        tomllib = None  # type: ignore[assignment]

DEFAULT_CLIENT_ID = "1565766221813776505"
DEFAULT_CROP = "440x45+740+50"
DEFAULT_DOWNLOAD_URL = "https://plarium.com/en/game/mech-arena/"
CROP_RE = re.compile(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$")

# Flags that are safe and useful to carry across a tray restart/dispatch.
VALUE_FLAGS: tuple[str, ...] = (
    "--config",
    "--client-id",
    "--crop",
    "--log-file",
    "--window-title",
    "--process-name",
    "--mode-delay",
    "--retries",
    "--retry-delay",
    "--poll",
    "--results-duration",
)


@dataclass(frozen=True)
class Button:
    label: str
    url: str


@dataclass(frozen=True)
class Config:
    # Discord application / presence assets
    client_id: str = DEFAULT_CLIENT_ID
    large_image: str = "mech_arena_logo"
    large_text: str = "Mech Arena"
    buttons: tuple[Button, ...] = (
        Button("Download Mech Arena", DEFAULT_DOWNLOAD_URL),
    )

    # HUD capture and classification
    crop: str = DEFAULT_CROP
    mode_lock_delay: float = 15.0
    lookup_retries: int = 3
    lookup_retry_delay: float = 2.0
    capture_timeout: float = 1.5
    edge_fraction: float = 0.15
    center_start_fraction: float = 0.35
    center_end_fraction: float = 0.65

    # Thresholds (brightness is 0-255)
    center_min_cpc: float = 95.0
    center_max_ffa: float = 95.0
    ratio_max_deathmatch: float = 0.88
    edge_min_deathmatch: float = 150.0
    ratio_min_cpc: float = 1.20
    min_brightness: float = 5.0

    # Timing
    results_display_duration: float = 10.0
    poll_interval: float = 2.0

    # Paths and matching
    log_file: Path = field(
        default_factory=lambda: Path.home() / ".cache/mech_arena_rpc.log"
    )
    window_title: str = "Mech Arena"
    process_name: str = "mecharena.exe"


def default_config_path() -> Path:
    """Return ``$XDG_CONFIG_HOME/mech-arena-rpc/config.toml``."""
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base).expanduser() / "mech-arena-rpc" / "config.toml"
    return Path.home() / ".config" / "mech-arena-rpc" / "config.toml"


def config_path_from_argv(argv: Iterable[str]) -> Path:
    """Read ``--config PATH`` without importing the daemon."""
    args = list(argv)
    if "--config" in args:
        try:
            return Path(args[args.index("--config") + 1]).expanduser()
        except IndexError:
            pass
    return default_config_path()


def parse_crop(geom: str) -> tuple[int, int, int, int]:
    """Parse ``WxH+X+Y`` into ``(width, height, x, y)``."""
    match = CROP_RE.match(geom.strip())
    if not match:
        raise ValueError(f"invalid crop geometry {geom!r}; expected WxH+X+Y")
    width, height, x, y = (int(part) for part in match.groups())
    if width <= 0 or height <= 0:
        raise ValueError("crop width and height must be positive")
    return width, height, x, y


def format_crop(width: int, height: int, x: int, y: int) -> str:
    return f"{width}x{height}{x:+d}{y:+d}"


def _coerce(
    name: str,
    value: Any,
    default: Any,
    cast: type,
    warnings: list[str],
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    allow_empty: bool = False,
) -> Any:
    try:
        if isinstance(value, bool) and cast in (int, float):
            raise ValueError("boolean is not a number")
        if cast is int:
            if isinstance(value, float) and not value.is_integer():
                raise ValueError("expected a whole number")
            value = int(value)
        elif cast is float:
            value = float(value)
            if not math.isfinite(value):
                raise ValueError("must be a finite number")
        elif cast is str:
            if not isinstance(value, str):
                raise ValueError("expected a string")
            value = value.strip()
            if not value and not allow_empty:
                raise ValueError("must not be empty")
        elif cast is Path:
            if not isinstance(value, str):
                raise ValueError("expected a path string")
            value = Path(value).expanduser()
        else:  # pragma: no cover - internal misuse
            raise ValueError(f"unsupported type {cast}")
    except (TypeError, ValueError):
        warnings.append(f"{name}: invalid value {value!r}; using {default!r}")
        return default

    if minimum is not None and value < minimum:
        warnings.append(f"{name}: {value!r} is below {minimum}; using {default!r}")
        return default
    if maximum is not None and value > maximum:
        warnings.append(f"{name}: {value!r} is above {maximum}; using {default!r}")
        return default
    return value


def _section(data: dict[str, Any], name: str, warnings: list[str]) -> dict[str, Any]:
    raw = data.get(name, {})
    if not isinstance(raw, dict):
        warnings.append(f"{name}: expected a table; ignoring it")
        return {}
    return raw


def _unknown(
    section: dict[str, Any], known: set[str], name: str, warnings: list[str]
) -> None:
    for key in section:
        if key not in known:
            warnings.append(f"{name}.{key}: unknown setting ignored")


def _parse_buttons(raw: Any, default: tuple[Button, ...], warnings: list[str]) -> tuple[Button, ...]:
    if not isinstance(raw, list):
        warnings.append("discord.buttons: expected an array; using default button")
        return default
    buttons: list[Button] = []
    if len(raw) > 2:
        warnings.append("discord.buttons: Discord allows at most 2; extra entries ignored")
    for index, entry in enumerate(raw[:2], start=1):
        if not isinstance(entry, dict):
            warnings.append(f"discord.buttons[{index}]: expected a table; ignored")
            continue
        label = entry.get("label")
        url = entry.get("url")
        if not isinstance(label, str) or not label.strip():
            warnings.append(f"discord.buttons[{index}].label: must be a non-empty string")
            continue
        if not isinstance(url, str) or not url.strip().startswith(("http://", "https://")):
            warnings.append(f"discord.buttons[{index}].url: must start with http:// or https://")
            continue
        buttons.append(Button(label.strip(), url.strip()))
    if raw and not buttons:
        warnings.append("discord.buttons: no valid entries; using default button")
        return default
    return tuple(buttons)


def from_mapping(data: dict[str, Any], base: Config | None = None) -> tuple[Config, list[str]]:
    """Build a validated config from a TOML mapping."""
    base = base or Config()
    warnings: list[str] = []

    if not isinstance(data, dict):
        return base, ["config: expected a TOML table; using defaults"]

    _unknown(data, {"discord", "hud", "timing", "logging", "window", "process"}, "config", warnings)

    discord = _section(data, "discord", warnings)
    _unknown(discord, {"client_id", "large_image", "large_text", "buttons"}, "discord", warnings)

    hud = _section(data, "hud", warnings)
    _unknown(
        hud,
        {
            "crop",
            "mode_lock_delay",
            "lookup_retries",
            "lookup_retry_delay",
            "capture_timeout",
            "edge_fraction",
            "center_start_fraction",
            "center_end_fraction",
            "thresholds",
        },
        "hud",
        warnings,
    )
    thresholds = hud.get("thresholds", {})
    if not isinstance(thresholds, dict):
        warnings.append("hud.thresholds: expected a table; using defaults")
        thresholds = {}
    _unknown(
        thresholds,
        {
            "center_min_cpc",
            "center_max_ffa",
            "ratio_max_deathmatch",
            "edge_min_deathmatch",
            "ratio_min_cpc",
            "min_brightness",
        },
        "hud.thresholds",
        warnings,
    )

    timing = _section(data, "timing", warnings)
    _unknown(timing, {"results_display_duration", "poll_interval"}, "timing", warnings)

    logging_section = _section(data, "logging", warnings)
    _unknown(logging_section, {"file"}, "logging", warnings)

    window = _section(data, "window", warnings)
    _unknown(window, {"title"}, "window", warnings)

    process = _section(data, "process", warnings)
    _unknown(process, {"name"}, "process", warnings)

    crop = _coerce(
        "hud.crop", hud.get("crop", base.crop), base.crop, str, warnings
    )
    try:
        parse_crop(crop)
    except ValueError as exc:
        warnings.append(f"hud.crop: {exc}; using {base.crop!r}")
        crop = base.crop

    raw_client_id = discord.get("client_id", base.client_id)
    if isinstance(raw_client_id, int):
        raw_client_id = str(raw_client_id)

    config = Config(
        client_id=_coerce(
            "discord.client_id",
            raw_client_id,
            base.client_id,
            str,
            warnings,
        ),
        large_image=_coerce(
            "discord.large_image",
            discord.get("large_image", base.large_image),
            base.large_image,
            str,
            warnings,
        ),
        large_text=_coerce(
            "discord.large_text",
            discord.get("large_text", base.large_text),
            base.large_text,
            str,
            warnings,
        ),
        buttons=_parse_buttons(discord.get("buttons", list(base.buttons)), base.buttons, warnings)
        if "buttons" in discord
        else base.buttons,
        crop=crop,
        mode_lock_delay=_coerce(
            "hud.mode_lock_delay",
            hud.get("mode_lock_delay", base.mode_lock_delay),
            base.mode_lock_delay,
            float,
            warnings,
            minimum=0,
        ),
        lookup_retries=_coerce(
            "hud.lookup_retries",
            hud.get("lookup_retries", base.lookup_retries),
            base.lookup_retries,
            int,
            warnings,
            minimum=0,
        ),
        lookup_retry_delay=_coerce(
            "hud.lookup_retry_delay",
            hud.get("lookup_retry_delay", base.lookup_retry_delay),
            base.lookup_retry_delay,
            float,
            warnings,
            minimum=0,
        ),
        capture_timeout=_coerce(
            "hud.capture_timeout",
            hud.get("capture_timeout", base.capture_timeout),
            base.capture_timeout,
            float,
            warnings,
            minimum=0.1,
        ),
        edge_fraction=_coerce(
            "hud.edge_fraction",
            hud.get("edge_fraction", base.edge_fraction),
            base.edge_fraction,
            float,
            warnings,
            minimum=0.01,
            maximum=0.49,
        ),
        center_start_fraction=_coerce(
            "hud.center_start_fraction",
            hud.get("center_start_fraction", base.center_start_fraction),
            base.center_start_fraction,
            float,
            warnings,
            minimum=0,
            maximum=0.99,
        ),
        center_end_fraction=_coerce(
            "hud.center_end_fraction",
            hud.get("center_end_fraction", base.center_end_fraction),
            base.center_end_fraction,
            float,
            warnings,
            minimum=0.01,
            maximum=1,
        ),
        center_min_cpc=_coerce(
            "hud.thresholds.center_min_cpc",
            thresholds.get("center_min_cpc", base.center_min_cpc),
            base.center_min_cpc,
            float,
            warnings,
            minimum=0,
            maximum=255,
        ),
        center_max_ffa=_coerce(
            "hud.thresholds.center_max_ffa",
            thresholds.get("center_max_ffa", base.center_max_ffa),
            base.center_max_ffa,
            float,
            warnings,
            minimum=0,
            maximum=255,
        ),
        ratio_max_deathmatch=_coerce(
            "hud.thresholds.ratio_max_deathmatch",
            thresholds.get("ratio_max_deathmatch", base.ratio_max_deathmatch),
            base.ratio_max_deathmatch,
            float,
            warnings,
            minimum=0,
        ),
        edge_min_deathmatch=_coerce(
            "hud.thresholds.edge_min_deathmatch",
            thresholds.get("edge_min_deathmatch", base.edge_min_deathmatch),
            base.edge_min_deathmatch,
            float,
            warnings,
            minimum=0,
            maximum=255,
        ),
        ratio_min_cpc=_coerce(
            "hud.thresholds.ratio_min_cpc",
            thresholds.get("ratio_min_cpc", base.ratio_min_cpc),
            base.ratio_min_cpc,
            float,
            warnings,
            minimum=0,
        ),
        min_brightness=_coerce(
            "hud.thresholds.min_brightness",
            thresholds.get("min_brightness", base.min_brightness),
            base.min_brightness,
            float,
            warnings,
            minimum=0,
            maximum=255,
        ),
        results_display_duration=_coerce(
            "timing.results_display_duration",
            timing.get("results_display_duration", base.results_display_duration),
            base.results_display_duration,
            float,
            warnings,
            minimum=0,
        ),
        poll_interval=_coerce(
            "timing.poll_interval",
            timing.get("poll_interval", base.poll_interval),
            base.poll_interval,
            float,
            warnings,
            minimum=0.1,
        ),
        log_file=_coerce(
            "logging.file",
            logging_section.get("file", str(base.log_file)),
            str(base.log_file),
            str,
            warnings,
        )
        if "file" in logging_section
        else base.log_file,
        window_title=_coerce(
            "window.title",
            window.get("title", base.window_title),
            base.window_title,
            str,
            warnings,
        ),
        process_name=_coerce(
            "process.name",
            process.get("name", base.process_name),
            base.process_name,
            str,
            warnings,
        ),
    )

    # `logging.file` needs a Path; the string coerce above keeps the warning text
    # readable while this conversion handles ~ and relative paths.
    if "file" in logging_section:
        try:
            config = replace(config, log_file=Path(str(config.log_file)).expanduser())
        except (TypeError, ValueError):
            warnings.append("logging.file: invalid path; using default")
            config = replace(config, log_file=base.log_file)

    if not (0 <= config.center_start_fraction < config.center_end_fraction <= 1):
        warnings.append(
            "hud.center_start_fraction/center_end_fraction: start must be lower "
            "than end; using defaults"
        )
        config = replace(
            config,
            center_start_fraction=base.center_start_fraction,
            center_end_fraction=base.center_end_fraction,
        )
    if config.edge_fraction * 2 >= 1:
        warnings.append("hud.edge_fraction: must leave room for the centre; using default")
        config = replace(config, edge_fraction=base.edge_fraction)

    return config, warnings


def load_config(
    path: Path | str | None = None,
    argv: Iterable[str] | None = None,
    *,
    create: bool = True,
) -> tuple[Config, list[str]]:
    """Load and validate a config file, then apply CLI overrides."""
    config_path = Path(path).expanduser() if path else default_config_path()
    warnings: list[str] = []
    data: dict[str, Any] = {}

    if config_path.exists():
        if tomllib is None:
            warnings.append(
                f"{config_path}: TOML support is unavailable (install tomli on Python 3.10); "
                "using defaults"
            )
        else:
            try:
                with config_path.open("rb") as handle:
                    data = tomllib.load(handle)
            except (OSError, tomllib.TOMLDecodeError) as exc:
                warnings.append(f"{config_path}: {exc}; using defaults")
    elif create:
        try:
            save_config(Config(), config_path, backup=False)
            warnings.append(f"created default config at {config_path}")
        except OSError as exc:
            warnings.append(f"{config_path}: could not create config ({exc}); using defaults")

    config, parse_warnings = from_mapping(data) if data else (Config(), [])
    warnings.extend(parse_warnings)

    if argv is not None:
        config, override_warnings = apply_cli_overrides(config, argv)
        warnings.extend(override_warnings)

    return config, warnings


def apply_cli_overrides(config: Config, argv: Iterable[str]) -> tuple[Config, list[str]]:
    """Apply supported ``--flag value`` overrides on top of a loaded config."""
    args = list(argv)
    warnings: list[str] = []

    def value_of(flag: str) -> str | None:
        if flag not in args:
            return None
        index = args.index(flag)
        if index + 1 >= len(args):
            warnings.append(f"{flag}: missing value")
            return None
        return args[index + 1]

    overrides: dict[str, Any] = {}
    rules: tuple[tuple[str, str, type, float | None, float | None], ...] = (
        ("--client-id", "client_id", str, None, None),
        ("--crop", "crop", str, None, None),
        ("--log-file", "log_file", Path, None, None),
        ("--window-title", "window_title", str, None, None),
        ("--process-name", "process_name", str, None, None),
        ("--mode-delay", "mode_lock_delay", float, 0, None),
        ("--retries", "lookup_retries", int, 0, None),
        ("--retry-delay", "lookup_retry_delay", float, 0, None),
        ("--poll", "poll_interval", float, 0.1, None),
        ("--results-duration", "results_display_duration", float, 0, None),
    )

    for flag, field_name, cast, minimum, maximum in rules:
        raw = value_of(flag)
        if raw is None:
            continue
        current = getattr(config, field_name)
        value = _coerce(
            f"{flag} ({field_name})",
            raw,
            current,
            cast,
            warnings,
            minimum=minimum,
            maximum=maximum,
        )
        if field_name == "crop":
            try:
                parse_crop(value)
            except ValueError as exc:
                warnings.append(f"{flag}: {exc}; keeping {current!r}")
                continue
        overrides[field_name] = value

    if overrides:
        config = replace(config, **overrides)
    return config, warnings


def persistent_cli_args(argv: Iterable[str]) -> list[str]:
    """Return config-related flags so a tray restart keeps the same settings."""
    args = list(argv)
    result: list[str] = []
    for flag in VALUE_FLAGS:
        if flag in args:
            index = args.index(flag)
            if index + 1 < len(args):
                result.extend([flag, args[index + 1]])
    return result


def _toml_string(value: str) -> str:
    # JSON string escapes are a valid subset of TOML basic-string escapes for
    # the values used here (quotes, backslashes, newlines, control characters).
    return json.dumps(value, ensure_ascii=False)


def _toml_number(value: float | int) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return repr(value)


def dump_config(config: Config) -> str:
    """Serialize a Config as the documented TOML layout."""
    lines = [
        "# Mech Arena Discord Rich Presence configuration",
        "# Edit this file, then use the tray menu: Reload Config.",
        "# Run `RPCA.py --calibrate` (tray: Calibrate HUD) to tune the HUD crop.",
        "",
        "[discord]",
        f"client_id = {_toml_string(config.client_id)}",
        f"large_image = {_toml_string(config.large_image)}",
        f"large_text = {_toml_string(config.large_text)}",
        "",
    ]

    if config.buttons:
        for button in config.buttons:
            lines.extend(
                [
                    "[[discord.buttons]]",
                    f"label = {_toml_string(button.label)}",
                    f"url = {_toml_string(button.url)}",
                    "",
                ]
            )
    else:
        lines.extend(["buttons = []", ""])

    lines.extend(
        [
            "[hud]",
            f"crop = {_toml_string(config.crop)}",
            f"mode_lock_delay = {_toml_number(config.mode_lock_delay)}",
            f"lookup_retries = {_toml_number(config.lookup_retries)}",
            f"lookup_retry_delay = {_toml_number(config.lookup_retry_delay)}",
            f"capture_timeout = {_toml_number(config.capture_timeout)}",
            f"edge_fraction = {_toml_number(config.edge_fraction)}",
            f"center_start_fraction = {_toml_number(config.center_start_fraction)}",
            f"center_end_fraction = {_toml_number(config.center_end_fraction)}",
            "",
            "[hud.thresholds]",
            f"center_min_cpc = {_toml_number(config.center_min_cpc)}",
            f"center_max_ffa = {_toml_number(config.center_max_ffa)}",
            f"ratio_max_deathmatch = {_toml_number(config.ratio_max_deathmatch)}",
            f"edge_min_deathmatch = {_toml_number(config.edge_min_deathmatch)}",
            f"ratio_min_cpc = {_toml_number(config.ratio_min_cpc)}",
            f"min_brightness = {_toml_number(config.min_brightness)}",
            "",
            "[timing]",
            f"results_display_duration = {_toml_number(config.results_display_duration)}",
            f"poll_interval = {_toml_number(config.poll_interval)}",
            "",
            "[logging]",
            f"file = {_toml_string(str(config.log_file))}",
            "",
            "[window]",
            f"title = {_toml_string(config.window_title)}",
            "",
            "[process]",
            f"name = {_toml_string(config.process_name)}",
            "",
        ]
    )
    return "\n".join(lines)


def save_config(
    config: Config,
    path: Path | str | None = None,
    *,
    backup: bool = True,
) -> Path:
    """Atomically write a config file, keeping a ``.bak`` copy by default."""
    config_path = Path(path).expanduser() if path else default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if backup and config_path.exists():
        try:
            shutil.copy2(config_path, config_path.with_name(config_path.name + ".bak"))
        except OSError:
            pass

    temporary = config_path.with_name(config_path.name + ".tmp")
    temporary.write_text(dump_config(config), encoding="utf-8")
    os.replace(temporary, config_path)
    return config_path
