from sc2.constants import UnitTypeId, AbilityId

from modubot.modules.module import BotModule

class ArchonMaker(BotModule):
  def __init__(self, bot, max_energy=300):
    super().__init__(bot)
    self.max_energy = max_energy

  async def on_step(self, iteration):
    for templar in self.units(UnitTypeId.HIGHTEMPLAR).filter(lambda t: t.energy <= self.max_energy):
      self.do(templar(AbilityId.MORPH_ARCHON))
