import math
from sc2.constants import UpgradeId, UnitTypeId

from sc2.dicts.unit_train_build_abilities import TRAIN_INFO

from .module import BotModule
from modubot.common import TrainingRequest, Urgency

class SimpleArmyBuilder(BotModule):
  def __init__(self, bot, get_priorities):
    super().__init__(bot)
    self.get_priorities = get_priorities
    bot.shared.warpgate_complete = False

  async def on_upgrade_complete(self, upgrade_id):
    if upgrade_id == UpgradeId.WARPGATERESEARCH:
      self.shared.warpgate_complete = True

  async def on_step(self, iteration):
    pylons = self.structures(UnitTypeId.PYLON).ready
    if pylons.empty:
      # not gonna be getting any units...
      return

    unit_priorities = self.get_priorities()
    urgency = Urgency.VERYLOW

    if self.shared.optimism < 1.4:
      urgency += 1
    elif self.shared.optimism < 1.3:
      urgency += 2
    elif self.shared.optimism < 1.2:
      urgency += 3
    elif self.shared.optimism < 1.1:
      urgency += 4
    elif self.shared.optimism < 1:
      urgency += 5
    elif self.shared.optimism < 0.9:
      urgency += 6
    elif self.shared.optimism < 0.8:
      urgency += 7
    elif self.shared.optimism < 0.7:
      urgency += 8

    requests = []
    for selected_unit in unit_priorities:
      requests.append(TrainingRequest(selected_unit, max(1, urgency)))
      # each unit request is lower priority than the last
      urgency -= 1

    return requests
