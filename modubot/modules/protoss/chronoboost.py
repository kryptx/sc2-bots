from sc2.constants import UnitTypeId, BuffId, AbilityId

from modubot.modules.module import BotModule

class ChronoBooster(BotModule):
  def __init__(self, bot, find_structure):
    super().__init__(bot)
    self.find_structure = find_structure

  async def on_step(self, iteration):
    nexuses = self.structures(UnitTypeId.NEXUS).filter(lambda nex: nex.energy >= 50)
    if nexuses.empty:
      return

    structure = self.find_structure()
    if not structure:
      return

    if not structure.has_buff(BuffId.CHRONOBOOSTENERGYCOST):
      self.do(nexuses.first(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, structure))
