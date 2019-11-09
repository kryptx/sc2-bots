from sc2 import Race
from sc2.constants import UnitTypeId

from modubot.common import StructureRequest, TrainingRequest, Urgency
from modubot.modules.module import BotModule

def compute_buffer_default(bot):
  return 3 * bot.townhalls.amount

class SupplyBufferer(BotModule):
  def __init__(self, bot, compute_buffer=compute_buffer_default):
    super().__init__(bot)
    self.desired_supply_buffer = 3
    self.compute_buffer = compute_buffer

  async def on_start(self):
    if self.race == Race.Protoss:
      self.get_supply_request = lambda urgency: StructureRequest(UnitTypeId.PYLON, urgency)
    if self.race == Race.Zerg:
      self.get_supply_request = lambda urgency: TrainingRequest(UnitTypeId.OVERLORD, urgency)
    if self.race == Race.Terran:
      self.get_supply_request = lambda urgency: StructureRequest(UnitTypeId.SUPPLYDEPOT, urgency)

  async def on_step(self, iteration):
    self.desired_supply_buffer = self.compute_buffer(self.bot)

    requests = []
    supply_urgency = self.determine_supply_urgency()

    if supply_urgency:
      requests.append(self.get_supply_request(supply_urgency))

    return requests

  def determine_supply_urgency(self):
    if self.supply_cap < 200 and not self.already_pending(self.shared.supply_type):
      if self.supply_left <= 0:
        return Urgency.EXTREME
      elif self.supply_left < self.desired_supply_buffer:
        return Urgency.HIGH
      elif self.supply_left < self.desired_supply_buffer * 1.5:
        return Urgency.LOW

    return Urgency.NONE
