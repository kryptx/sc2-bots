import random
import math
from git import Repo

import sc2
from sc2 import Race, Difficulty
from sc2.constants import *
from sc2.player import Bot, Computer
from sc2.unit_command import UnitCommand
from sc2.units import Units
from sc2.position import Point2

from advisors.p.economy import ProtossEconomyAdvisor
from advisors.p.tactics import ProtossTacticsAdvisor
from advisors.p.scouting import ProtossScoutingAdvisor
from advisors.p.vp_strategy import PvPStrategyAdvisor

from planners.protoss import ProtossBasePlanner

from common import Urgency, list_flatten

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
    self.highest_optimism_reported = 1
    self.lowest_optimism_reported = 1
    self.advisor_data = AdvisorData()
    self.tagged_units = UnitAllocation()
    self.rally_point = None

    self.desired_supply_buffer = 3
    self.warpgate_complete = False

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

  async def chit_chat(self):
    if not self.version_reported:
      self.version_reported = True
      repo = Repo(search_parent_directories=True)
      if not repo.is_dirty():
        sha = repo.head.object.hexsha
        await self.chat_send("AdvisorBot verified hash: " + sha[0:10])
      await self.chat_send("(glhf)(cake)(sc2)")
    if self.time < 60:
      return
    if self.highest_optimism_reported < 5 and self.strategy_advisor.optimism > 5:
      self.highest_optimism_reported = 5
      await self.chat_send("I think I got this")

    if self.highest_optimism_reported < 10 and self.strategy_advisor.optimism > 10:
      self.highest_optimism_reported = 10
      await self.chat_send("(flex) Advisors did it again folks (flex)")

    enemy_fighters = self.enemy_units.filter(lambda u: u.type_id not in (UnitTypeId.PROBE, UnitTypeId.DRONE, UnitTypeId.SCV))
    if enemy_fighters.amount > 10:
      if self.lowest_optimism_reported > 0.2 and self.strategy_advisor.optimism < 0.2:
        self.lowest_optimism_reported = 0.2
        await self.chat_send("whoa... (scared) ")

      if self.lowest_optimism_reported > 0.1 and self.strategy_advisor.optimism < 0.1:
        self.lowest_optimism_reported = 0.1
        await self.chat_send("this is not good. (salty)")

  async def on_step(self, iteration):
    await self.chit_chat()
    requests = []
    self.desired_supply_buffer = 2 + self.structures({ UnitTypeId.WARPGATE, UnitTypeId.GATEWAY }).amount * 2.5
    for advisor in self.advisors:
      advisorResult = await advisor.tick()
      if advisorResult == None:
        print("exiting due to surrender")
        return
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
    if upgrade == UpgradeId.WARPGATERESEARCH:
      self.warpgate_complete = True
    for advisor in self.advisors:
      await advisor.on_upgrade_complete(upgrade)

  async def on_unit_destroyed(self, unit):
    for advisor in self.advisors:
      await advisor.on_unit_destroyed(unit)

  def bases_centroid(self):
    return Point2.center([nex.position for nex in self.townhalls])

  def unallocated(self, unit_types=None, urgency=Urgency.NONE):
    units = self.units(unit_types) if unit_types else self.units.filter(lambda u: u.type_id != UnitTypeId.PROBE)
    return units.tags_not_in(list_flatten([
      list(objective.allocated)
      for objective in self.strategy_advisor.objectives
      if objective.urgency and objective.urgency >= urgency
    ]) + list(self.tagged_units.scouting))

maps = [
  "(2)16-BitLE",
  "(2)DreamcatcherLE",
  "(2)LostandFoundLE",
  "(2)RedshiftLE",
  "(4)DarknessSanctuaryLE",
  "AbiogenesisLE",
  "AbyssalReefLE",
  "AcidPlantLE",
  "AcolyteLE",
  "AcropolisLE",
  "AscensionToAiurLE",
  "AutomatonLE",
  "BackwaterLE",
  "BattleontheBoardwalkLE",
  "BelShifVestigeLE",
  "BlackpinkLE",
  "BloodBoilLE",
  "BlueshiftLE",
  "CactusValleyLE",
  "CatalystLE",
  "CeruleanFallLE",
  "CyberForestLE",
  "DefendersLandingLE",
  "DiscoBloodbathLE",
  "EastwatchLE",
  "EphemeronLE",
  "FrostLE",
  "HonorGroundsLE",
  "InterloperLE",
  "KairosJunctionLE",
  "KingsCoveLE",
  "MechDepotLE",
  "NeonVioletSquareLE",
  "NewkirkPrecinctTE",
  "NewRepugnancyLE",
  "OdysseyLE",
  "PaladinoTerminalLE",
  "ParaSiteLE",
  "PortAleksanderLE",
  "ProximaStationLE",
  "SequencerLE",
  "StasisLE",
  "ThunderbirdLE",
  "TritonLE",
  "TurboCruise'84LE",
  "WintersGateLE",
  "WorldofSleepersLE"
]

def main():
  sc2.run_game(sc2.maps.get(random.choice(maps)), [
    Bot(Race.Protoss, AdvisorBot()),
    Computer(Race.Protoss, Difficulty.VeryHard)
  ], realtime=False)

if __name__ == '__main__':
  main()
