import math
from sc2.constants import UpgradeId, UnitTypeId

from sc2.dicts.unit_train_build_abilities import TRAIN_INFO

from .module import BotModule
from modubot.common import TrainingRequest, WarpInRequest, Urgency

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
    pylon = pylons.closest_to(self.game_info.map_center)
    urgency = Urgency.LOW

    if self.time < 240:
      urgency += 2
      if self.shared.enemy_is_rushing:
        urgency += 2
    if self.shared.optimism < 1.1:
      urgency += 1
    if self.shared.optimism <= 1:
      urgency += 1
    if self.shared.optimism < 0.9:
      urgency += 1
    if self.shared.optimism < 0.8:
      urgency += 1
    if self.shared.optimism < 0.7:
      urgency += 1

    requests = []
    for selected_unit in unit_priorities:
      if self.shared.warpgate_complete:
        pos = pylon.position.to2.random_on_distance([2, 5])
        placement = await self.find_placement(TRAIN_INFO[UnitTypeId.WARPGATE][selected_unit]['ability'], pos, placement_step=1)
        if placement:
          requests.append(WarpInRequest(selected_unit, placement, max(1, urgency)))
        else:
          self.log.warn(f"Could not find placement for {selected_unit}")
      else:
        requests.append(TrainingRequest(selected_unit, max(1, urgency)))
      # each unit request is lower priority than the last
      urgency -= 1

    return requests