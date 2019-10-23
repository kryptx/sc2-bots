from sc2.constants import UnitTypeId, BuffId, AbilityId

from modubot.common import TrainingRequest, StructureRequest, Urgency
from modubot.modules.module import BotModule

class CreepSpreader(BotModule):
  def __init__(self, bot):
    super().__init__(bot)
    bot.shared.unused_tumors = set()
    self.last_tumor_check = 0

  async def on_step(self, iteration):
    if self.time - self.last_tumor_check > 2:
      self.last_tumor_check = self.time
      await self.find_unused_tumors()

    if self.shared.unused_tumors:
      return [ StructureRequest(UnitTypeId.CREEPTUMOR, Urgency.HIGH) ]

    ready_queens = self.units(UnitTypeId.QUEEN).filter(lambda q: q.energy > 30)
    if ready_queens.exists and self.time < 360:
      return [ StructureRequest(UnitTypeId.CREEPTUMOR, Urgency.HIGH) ]

  async def find_unused_tumors(self):
    all_tumors = self.structures(UnitTypeId.CREEPTUMOR).ready
    for tumor in all_tumors:
      abilities = await self.get_available_abilities(tumor)
      if AbilityId.BUILD_CREEPTUMOR_TUMOR in abilities:
        self.shared.unused_tumors.add(tumor.tag)
      else:
        # this should be handled by the planner -- but, just in case
        self.shared.unused_tumors.discard(tumor.tag)