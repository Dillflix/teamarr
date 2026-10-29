"""DAZN Canada NSL squash and Beatdown fight-card broadcast discovery."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from teamarr.core.broadcast import BroadcastSession
from teamarr.services.dazn_tennis import DAZNTennisScheduleService, _parse_dazn_schedule

# Observed in DAZN Canada's public EPG on 2026-10-29. Match provider identities,
# not titles: an unrelated MMA promotion or similarly named show is not Beatdown.
COMPETITIONS = {
    "vpfggrvk32lz1juwvto8z18vw": ("nsl", "Squash", "event_coverage"),
    "fzncxnbx6rxp1ix28rvs1t3lf": ("beatdown", "MMA", "fight_card"),
}


class DAZNSportsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    competitions: list[Literal["nsl", "beatdown"]] = ["nsl", "beatdown"]


def parse_dazn_sports(body: dict, day: date, received_at: datetime) -> list[BroadcastSession]:
    return _parse_dazn_schedule(body, day, received_at, COMPETITIONS)


class DAZNSportsScheduleService(DAZNTennisScheduleService):
    parse = staticmethod(parse_dazn_sports)
