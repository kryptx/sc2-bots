import random
import math
from git import Repo

import sc2
from sc2 import Race, Difficulty
from sc2.constants import *
from sc2.player import Bot, Computer
from sc2.unit_command import UnitCommand
from sc2.units import Units

from advisors.p.economy import ProtossEconomyAdvisor
from advisors.p.tactics import ProtossTacticsAdvisor
from advisors.p.scouting import ProtossScoutingAdvisor
from advisors.p.vp_strategy import PvPStrategyAdvisor

from common import Urgency, ProtossBasePlanner

def urgencyValue(req):
  return req.urgency

### EL BOT ###

class AdvisorData():
  def __init__(self):
    self.strategy = dict()
    self.tactics = dict()
    self.economy = dict()
    self.scouting = dict()

class UnitAllocation():
  def __init__(self):
    self.strategy = set()
    self.tactics = set()
    self.economy = set()
    self.scouting = set()

class AdvisorBot(sc2.BotAI):

  def __init__(self):
    self.version_reported = False
    self.advisor_data = AdvisorData()
    self.tagged_units = UnitAllocation()
    self.rally_point = None

    self.desired_supply_buffer = 3

    self.planner = ProtossBasePlanner(self)
    self.economy_advisor = ProtossEconomyAdvisor(self)
    self.strategy_advisor = PvPStrategyAdvisor(self)
    self.tactics_advisor = ProtossTacticsAdvisor(self)
    self.scouting_advisor = ProtossScoutingAdvisor(self)

    self.advisors = [
      self.economy_advisor,
      self.strategy_advisor,
      self.tactics_advisor,
      self.scouting_advisor
    ]

  async def report_version(self):
    if not self.version_reported:
      self.version_reported = True
      repo = Repo(search_parent_directories=True)
      if not repo.is_dirty():
        sha = repo.head.object.hexsha
        await self.chat_send("AdvisorBot verified hash: " + sha[0:10])

  async def on_step(self, iteration):
    await self.report_version()
    requests = []
    self.desired_supply_buffer = 2 + self.structures({ UnitTypeId.WARPGATE, UnitTypeId.GATEWAY }).amount * 2.5
    for advisor in self.advisors:
      advisorResult = await advisor.tick()
      requests.extend(advisorResult)

    requests.sort(key=urgencyValue, reverse=True)
    fulfill_threshold = None
    while requests:
      if fulfill_threshold and requests[0].urgency < fulfill_threshold:
        break

      request = requests.pop(0)
      if request.urgency and self.can_afford(request.expense):
        action = await request.fulfill(self)
        if action:
          self.do(action)
      else:
        fulfill_threshold = request.urgency

  async def on_upgrade_complete(self, upgrade):
    for advisor in self.advisors:
      await advisor.on_upgrade_complete(upgrade)

  async def on_unit_destroyed(self, unit):
    for advisor in self.advisors:
      await advisor.on_unit_destroyed(unit)

def main():
  sc2.run_game(sc2.maps.get("TritonLE"), [
    Bot(Race.Protoss, AdvisorBot()),
    Computer(Race.Protoss, Difficulty.VeryHard)
  ], realtime=False)

if __name__ == '__main__':
  main()
