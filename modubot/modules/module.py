from sc2.units import Units
from modubot.common import Urgency

class BotModule(object):
  def __init__(self, bot):
    self.bot = bot

  def __getattr__(self, name):
    return getattr(self.bot, name)

  async def on_step(self, iteration):
    raise NotImplementedError("You must implement this function")


  # modules that "claim" units should override these two properties and deallocate method
  @property
  def allocated(self):
    return set()

  @property
  def urgency(self):
    return Urgency.NONE

  def deallocate(self, tag_set):
    return

  # Some other methods that are available
  async def on_start(self):
    pass

  async def on_end(self, game_result):
    pass

  async def on_unit_created(self, unit):
    pass

  async def on_unit_destroyed(self, tag):
    pass

  async def on_building_construction_started(self, unit):
    pass

  async def on_building_construction_complete(self, unit):
    pass

  async def on_upgrade_complete(self, upgrade_id):
    pass
