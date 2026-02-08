"""Entry point for rvc2hass: python -m rvc2hass."""

import logging
import sys

from .config import load_profile, parse_args


def main():
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    log = logging.getLogger("rvc2hass")

    try:
        profile = load_profile(args.profile)
    except (FileNotFoundError, ValueError) as e:
        log.error("Failed to load profile: %s", e)
        sys.exit(1)

    log.info("Loaded profile: %s", profile.info.name)
    log.info(
        "Entities: %d lights, %d switches, %d covers, %d sensors, %d binary sensors",
        len(profile.lights),
        len(profile.switches),
        len(profile.covers),
        len(profile.sensors),
        len(profile.binary_sensors),
    )

    if args.discover:
        log.info("Discovery mode — scanning bus for %d seconds...", args.discover_duration)
        # Discovery mode will be implemented in step 4
        from .discovery import run_discovery
        run_discovery(profile, args)
    else:
        log.info("Starting rvc2hass service...")
        # Main service loop will be implemented in later steps
        from .app import run_service
        run_service(profile, args)


if __name__ == "__main__":
    main()
