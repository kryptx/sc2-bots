import sc2
from sc2.constants import UnitTypeId
from sc2 import Race
from sc2.units import Units

from .module import BotModule
from modubot.common import optimism, is_worker, Urgency
from modubot.harassment.mission import HarassmentMissionStatus

class Harasser(BotModule):
  def __init__(self, bot, missions=[]):
    super().__init__(bot)
    self.missions = missions

  async def on_step(self, iteration):
    requests = []
    for mission in self.missions:
      requests.extend(await mission.on_step() or [])

    self.missions = [ m for m in self.missions if m.status != HarassmentMissionStatus.COMPLETE ]

    return requests

  @property
  def allocated(self):
    harassers = set()
    for mission in self.missions:
      harassers = harassers.union(mission.active_attackers)
    return harassers

  @property
  def urgency(self):
    return Urgency.VERYHIGH

  def deallocate(self, tag_set):
    for mission in self.missions:
      mission.active_attackers.difference_update(tag_set)
