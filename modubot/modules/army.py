import math
from sc2.constants import UpgradeId, UnitTypeId

from .module import BotModule
from modubot.common import BuildRequest, Urgency

class SimpleArmyBuilder(BotModule):
  def __init__(self, bot, get_priorities):
    super().__init__(bot)
    self.get_priorities = get_priorities

  async def on_step(self, iteration):
    unit_priorities = self.get_priorities()
    urgency = Urgency.VERYLOW

    if self.shared.optimism < 0.2:
      urgency = Urgency.EXTREME
    elif self.shared.optimism < 0.4:
      urgency = Urgency.VERYHIGH
    elif self.shared.optimism < 0.6:
      urgency = Urgency.HIGH
    elif self.shared.optimism < 0.8:
      urgency = Urgency.MEDIUMHIGH
    elif self.shared.optimism < 1:
      urgency = Urgency.MEDIUM
    elif self.shared.optimism < 1.2:
      urgency = Urgency.MEDIUMLOW
    elif self.shared.optimism < 1.4:
      urgency = Urgency.LOW

    requests = []
    for selected_unit in unit_priorities:
      requests.append(BuildRequest(selected_unit, max(1, urgency)))
      # each unit request is lower priority than the last
      urgency -= 1

    self.log_unit_breakdown()

    return requests

  def log_unit_breakdown(self):
    units = {}
    for u in self.units:
      tid = str(u.type_id)
      cost = u._type_data._proto.food_required
      if tid in units:
        units[tid] += cost
      else:
        units[tid] = cost

    for unit_type, supply_used in units.items():
      self.log.info({
        "message": "Unit count",
        "unit_type": unit_type,
        "supply_used": supply_used,
        "game_time": self.bot.time
      })
