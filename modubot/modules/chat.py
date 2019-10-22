
from git import Repo
import sc2
from sc2.constants import UnitTypeId

from .module import BotModule
from modubot.common import is_worker

class OptimismChatter(BotModule):
  def __init__(self, bot):
    super().__init__(bot)
    self.version_reported = False
    self.highest_optimism_reported = 1
    self.lowest_optimism_reported = 1

  async def on_step(self, iteration):
    if not self.version_reported:
      self.version_reported = True
      repo = Repo(search_parent_directories=True)
      if not repo.is_dirty():
        sha = repo.head.object.hexsha
        await self.chat_send("ModuBot verified hash: " + sha[0:10])
      await self.chat_send("(glhf)(cake)(sc2)")
    if self.time < 120:
      return
    if self.highest_optimism_reported < 10 and self.shared.optimism > 10:
      self.highest_optimism_reported = 10
      await self.chat_send("-- Enemy contained --")

    if self.highest_optimism_reported < 50 and self.shared.optimism > 50:
      self.highest_optimism_reported = 50
      await self.chat_send("-- Victory confidence 99% --")

    enemy_fighters = self.enemy_units.filter(lambda u: not is_worker(u))
    if enemy_fighters.amount > 10:
      if self.lowest_optimism_reported > 0.3 and self.shared.optimism < 0.3:
        self.lowest_optimism_reported = 0.3
        await self.chat_send("whoa... (scared) ")

      if self.lowest_optimism_reported > 0.15 and self.shared.optimism < 0.15:
        self.lowest_optimism_reported = 0.15
        await self.chat_send("this is not good. (salty)")
