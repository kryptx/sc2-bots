import math
from sc2.constants import UpgradeId, UnitTypeId

from sc2.dicts.unit_train_build_abilities import TRAIN_INFO

from .module import BotModule
from modubot.common import BuildRequest, Urgency

class SimpleArmyBuilder(BotModule):
  def __init__(self, bot, get_priorities):
    super().__init__(bot)
    self.get_priorities = get_priorities

  async def on_step(self, iteration):
    unit_priorities = self.get_priorities()
    urgency = Urgency.VERYLOW

    if self.shared.optimism < 2:
      urgency = Urgency.LOW
    elif self.shared.optimism < 1.8:
      urgency = Urgency.MEDIUMLOW
    elif self.shared.optimism < 1.6:
      urgency = Urgency.MEDIUM
    elif self.shared.optimism < 1.4:
      urgency = Urgency.MEDIUMHIGH
    elif self.shared.optimism < 1.2:
      urgency = Urgency.HIGH
    elif self.shared.optimism < 1:
      urgency = Urgency.VERYHIGH
    elif self.shared.optimism < 0.9:
      urgency = Urgency.EXTREME

    requests = []
    for selected_unit in unit_priorities:
      requests.append(BuildRequest(selected_unit, max(1, urgency)))
      # each unit request is lower priority than the last
      urgency -= 1

    return requests
