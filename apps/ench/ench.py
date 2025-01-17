"""AppDaemon EnCh app.

  @benleb / https://github.com/benleb/ad-ench

ench:
  module: ench
  class: EnCh
  exclude:
    - sensor.out_of_order
    - binary_sensor.always_unavailable
  battery
    interval_min: 180
    min_level: 20
  unavailable
    interval_min: 60
  notify: notify.me
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union

from apps.ench.adutils import adutils
try:
    import hassapi as hass  # newer variant
except:
    # Should be removed / simplified to the "newer variant" if https://github.com/benleb/ad-ench/issues/1
    import appdaemon.plugins.hass.hassapi as hass


APP_NAME = "EnCh"
APP_ICON = "👩‍⚕️"
APP_VERSION = "0.4.4"

BATTERY_MIN_LEVEL = 20
INTERVAL_BATTERY_MIN = 180
INTERVAL_BATTERY = INTERVAL_BATTERY_MIN / 60

INTERVAL_UNAVAILABLE_MIN = 60
INTERVAL_UNAVAILABLE = INTERVAL_UNAVAILABLE_MIN / 60

EXCLUDE = ["binary_sensor.updater", "persistent_notification.config_entry_discovery"]
BAD_STATES = ["unavailable", "unknown"]

ICONS = dict(battery="🔋", unavailable="⁉️ ", unknown="❓")


class EnCh(hass.Hass):  # type: ignore
    """ench."""

    def initialize(self) -> None:
        """Register API endpoint."""
        self.cfg: Dict[str, Any] = dict()
        self.cfg["notify"] = self.args.get("notify")
        self.cfg["show_friendly_name"] = bool(self.args.get("show_friendly_name", True))

        # battery check
        if "battery" in self.args:

            battery_cfg = self.args.get("battery")

            # temp. to be compatible with the old interval
            if "interval_min" in battery_cfg:
                interval_min = battery_cfg.get("interval_min")
            elif "interval" in battery_cfg:
                interval_min = battery_cfg.get("interval") * 60
            else:
                interval_min = INTERVAL_BATTERY_MIN

            self.cfg["battery"] = dict(
                interval_min=int(interval_min),
                min_level=int(battery_cfg.get("min_level", BATTERY_MIN_LEVEL)),
            )

            # schedule check
            self.run_every(
                self.check_battery,
                self.datetime() + timedelta(seconds=120),
                self.cfg["battery"]["interval_min"] * 60,
            )

        # unavailable check
        if self.args.get("unavailable"):

            states_cfg = self.args.get("unavailable")

            # temp. to be compatible with the old interval
            if "interval_min" in states_cfg:
                interval_min = states_cfg.get("interval_min")
            elif "interval" in states_cfg:
                interval_min = states_cfg.get("interval") * 60
            else:
                interval_min = INTERVAL_UNAVAILABLE_MIN

            self.cfg["unavailable"] = dict(interval_min=int(interval_min))

            self.run_every(
                self.check_unavailable,
                self.datetime() + timedelta(seconds=120),
                self.cfg["unavailable"]["interval_min"] * 60,
            )

        # merge excluded entities
        exclude = set(EXCLUDE)
        exclude.update([e.lower() for e in self.args.get("exclude", set())])
        self.cfg["exclude"] = sorted(list(exclude))

        # set units
        self.cfg.setdefault(
            "_units", dict(interval="h", interval_min="min", min_level="%")
        )

        # init adutils
        self.adu = adutils.ADutils(
            APP_NAME, self.cfg, icon=APP_ICON, ad=self, show_config=True
        )

        # temp. warning bevore removing "interval"
        if "interval" in battery_cfg:
            self.adu.log(f"", icon="🧨")
            self.adu.log(
                f" Please convert your {self.hl('interval')} (in hours) setting to {self.hl('interval_min')} (in minutes)",
                icon="🧨",
            )
            self.adu.log(
                f" The {self.hl('interval')} option will be removed in  future release",
                icon="🧨",
            )
            self.adu.log(f"", icon="🧨")

    def check_battery(self, _: Any) -> None:
        """Handle scheduled checks."""
        results: List[str] = []

        self.adu.log(f"Checking entities for low battery levels...", APP_ICON)

        entities = filter(
            lambda x: x.lower() not in self.cfg["exclude"], self.get_state()
        )

        for entity in sorted(entities):
            try:
                attrs = self.get_state(entity_id=entity, attribute="all")
            except TypeError as error:
                self.adu.log(f"Failed to get state for {entity}: {error}")

            battery_level = attrs["attributes"].get("battery_level")
            if battery_level and battery_level <= self.cfg["battery"]["min_level"]:
                results.append(entity)
                self.adu.log(
                    f"{self._name(entity)} has low "
                    f"{self.hl(f'battery → {self.hl(int(battery_level))}')}% | "
                    f"last update: {self.last_update(entity)}",
                    icon=ICONS["battery"],
                )

        # send notification
        if self.cfg["notify"] and results:
            self.call_service(
                str(self.cfg["notify"]).replace(".", "/"),
                message=f"{ICONS['battery']} Battery low ({len(results)}): "
                f"{', '.join([e for e in results])}",
            )

        self._print_result("battery", results, "low battery levels")

    def check_unavailable(self, _: Any) -> None:
        """Handle scheduled checks."""
        results: List[str] = []

        self.adu.log(f"Checking entities for unavailable/unknown state...", APP_ICON)

        entities = filter(
            lambda x: x.lower() not in self.cfg["exclude"], self.get_state()
        )

        for entity in sorted(entities):

            try:
                attributes = self.get_state(entity_id=entity, attribute="all")
            except TypeError as error:
                self.adu.log(f"Failed to get state for {entity}: {error}")

            state = attributes.get("state")
            if state in BAD_STATES and entity not in results:
                results.append(entity)
                self.adu.log(
                    f"{self._name(entity)} is {self.hl(state)} | "
                    f"last update: {self.last_update(entity)}",
                    icon=ICONS[state],
                )

        # send notification
        if self.cfg["notify"] and results:
            self.call_service(
                str(self.cfg["notify"]).replace(".", "/"),
                message=f"{APP_ICON} Unavailable entities ({len(results)}): "
                f"{', '.join([e for e in results])}",
            )

        self._print_result("unavailable", results, "unavailable/unknown state")

    def _name(self, entity: str) -> Optional[str]:
        name: Optional[str] = None
        if self.cfg["show_friendly_name"]:
            name = self.friendly_name(entity)
        else:
            name = self._highlight_entity(entity)
        return name

    def _print_result(self, check: str, entities: List[str], reason: str) -> None:
        entites_found = len(entities)
        if entites_found > 0:
            self.adu.log(
                f"{self.hl(f'{entites_found} entities')} with {self.hl(reason)}!",
                APP_ICON,
            )
        else:
            self.adu.log(f"no entities with {reason} found", APP_ICON)

    # todo  move these methods to adutils lib
    def last_update(self, entity: str) -> str:
        lu_date, lu_time = self._to_localtime(entity, "last_updated")
        last_updated = str(lu_time.strftime("%H:%M:%S"))
        if lu_date != self.date():
            last_updated = f"{last_updated} ({lu_date.strftime('%Y-%m-%d')})"
        return last_updated

    def _to_localtime(self, entity: str, attribute: str) -> Any:
        attributes = self.get_state(entity_id=entity, attribute="all")
        time_utc = datetime.fromisoformat(attributes[attribute])
        tzone = timezone(
            timedelta(minutes=self.get_tz_offset()), name=self.get_timezone()
        )
        time_local = time_utc.astimezone(tzone)
        return (time_local.date(), time_local.time())

    def _highlight_entity(self, entity: str) -> str:
        domain, entity = self.split_entity(entity)
        return f"{domain}.{self.hl(entity)}"

    def hl(self, text: Union[int, str, None]) -> str:
        return f"\033[1m{text}\033[0m"
