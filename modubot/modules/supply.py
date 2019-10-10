from sc2.constants import UnitTypeId

from modubot.common import StructureRequest, Urgency
from modubot.modules.module import BotModule

def compute_buffer_default(bot):
  return 2 + bot.structures({ UnitTypeId.WARPGATE, UnitTypeId.GATEWAY }).amount * 2.5

class SupplyBufferer(BotModule):
  def __init__(self, bot, compute_buffer=compute_buffer_default):
    super().__init__(bot)
    self.desired_supply_buffer = 3
    self.compute_buffer = compute_buffer

  async def on_step(self, iteration):
    self.desired_supply_buffer = self.compute_buffer(self.bot)

    requests = []
    pylon_urgency = self.determine_pylon_urgency()

    if pylon_urgency:
      requests.append(StructureRequest(UnitTypeId.PYLON, self.planner, pylon_urgency))

    return requests

  def determine_pylon_urgency(self):
    pylon_urgency = Urgency.NONE

    if self.supply_cap < 200 and not self.already_pending(UnitTypeId.PYLON):
      if self.supply_left <= 0:
        pylon_urgency = Urgency.EXTREME
      if self.supply_left < self.desired_supply_buffer:
        pylon_urgency = Urgency.VERYHIGH
      elif self.supply_left < self.desired_supply_buffer * 1.5:
        pylon_urgency = Urgency.LOW

    return pylon_urgency
