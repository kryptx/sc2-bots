
from sc2.constants import EffectId

from .module import BotModule
from modubot.common import ResearchRequest

class Upgrader(BotModule):
  def __init__(self, bot, upgrade_sets=dict()):
    super().__init__(bot)
    self.upgrade_sets = upgrade_sets

  async def on_upgrade_complete(self, upgrade_id):
    for urgency in self.upgrade_sets.keys():
      self.upgrade_sets[urgency] = [
        [ upgrade
          for upgrade in group
          if upgrade != upgrade_id ]
        for group in self.upgrade_sets[urgency]
        if group and (len(group) > 1 or group[0] != upgrade_id)
      ]

  async def on_step(self, iteration):
    requests = []
    for urgency in self.upgrade_sets.keys():
      for group in self.upgrade_sets[urgency]:
        self.log.debug(f"Upgrade group: {group}")
        if not self.already_pending_upgrade(group[0]):
          requests.append(ResearchRequest(group[0], urgency))
    return requests
