import random
import math

import sc2
from sc2 import Race, Difficulty
from sc2.constants import *
from sc2.player import Bot, Computer
from sc2.unit_command import UnitCommand
from sc2.units import Units

from advisors.p.economy import ProtossEconomyAdvisor
from advisors.p.tactics import ProtossTacticsAdvisor
from advisors.p.vp_strategy import PvPStrategyAdvisor

from common import Urgency

def urgencyValue(req):
  return req.urgency

### EL BOT ###

class MacroManagerBot(sc2.BotAI):
  def __init__(self):
    self.economy_advisor = ProtossEconomyAdvisor(self)
    self.strategy_advisor = PvPStrategyAdvisor(self)
    self.tactics_advisor = ProtossTacticsAdvisor(self)
    self.scout_tags = []
    self.attacker_tags = []
    self.rally_point = None

    self.desired_supply_buffer = 3

    self.advisors = [
      self.economy_advisor,
      self.strategy_advisor,
      self.tactics_advisor
    ]

  async def on_step(self, iteration):
    requests = []
    self.desired_supply_buffer = math.sqrt(self.supply_used)
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

def main():
  sc2.run_game(sc2.maps.get("AcropolisLE"), [
    Bot(Race.Protoss, MacroManagerBot()),
    Computer(Race.Protoss, Difficulty.VeryHard)
  ], realtime=False)

if __name__ == '__main__':
  main()
