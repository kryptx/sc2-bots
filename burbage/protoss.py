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
from sc2.data import AIBuild

from advisors.p.economy import ProtossEconomyAdvisor
from advisors.p.tactics import ProtossTacticsAdvisor
from advisors.p.scouting import ProtossScoutingAdvisor
from advisors.p.vp_strategy import PvPStrategyAdvisor, AttackObjective, DefenseObjective

from planners.protoss import ProtossBasePlanner

from common import Urgency, list_flatten
all_unit_ids = [name for name, member in UnitTypeId.__members__.items()]

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
    # chat stuff
    self.version_reported = False
    self.highest_optimism_reported = 1
    self.lowest_optimism_reported = 1
    self.last_camera_move = 0

    # stuff that needs to be redesigned
    self.advisor_data = AdvisorData()
    self.tagged_units = UnitAllocation()

    # Various info that's often needed
    self.enemy_race = None
    self.rally_point = None
    self.desired_supply_buffer = 3

    # protoss specific still...
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

  ##
  # If you get this error:
  # File "burbage/protoss.py", line 69
  #   async def chit_chat(self):
  #           ^
  # SyntaxError: invalid syntax
  #
  # It's because you need the virtualenv:
  # $ source botenv/bin/activate
  #
  async def chit_chat(self):
    if not self.version_reported:
      self.version_reported = True
      repo = Repo(search_parent_directories=True)
      if not repo.is_dirty():
        sha = repo.head.object.hexsha
        await self.chat_send("AdvisorBot verified hash: " + sha[0:10])
      await self.chat_send("(glhf)(cake)(sc2)")
    if self.time < 120:
      return
    if self.highest_optimism_reported < 10 and self.strategy_advisor.optimism > 10:
      self.highest_optimism_reported = 10
      await self.chat_send("I think I got this")

    if self.highest_optimism_reported < 50 and self.strategy_advisor.optimism > 50:
      self.highest_optimism_reported = 50
      await self.chat_send("(flex) Advisors did it again folks (flex)")

    enemy_fighters = self.enemy_units.filter(lambda u: u.type_id not in (UnitTypeId.PROBE, UnitTypeId.DRONE, UnitTypeId.SCV))
    if enemy_fighters.amount > 10:
      if self.lowest_optimism_reported > 0.2 and self.strategy_advisor.optimism < 0.2:
        self.lowest_optimism_reported = 0.2
        await self.chat_send("whoa... (scared) ")

      if self.lowest_optimism_reported > 0.1 and self.strategy_advisor.optimism < 0.1:
        self.lowest_optimism_reported = 0.1
        await self.chat_send("this is not good. (salty)")

  async def set_camera(self):
    if self.last_camera_move < self.time - 2:
      self.last_camera_move = self.time

      # if we're attacking
      for objective in self.strategy_advisor.objectives:
        if isinstance(objective, AttackObjective):
          await self._client.move_camera(objective.units.closest_to(objective.target).position)
          return

      # if we're defending
      for objective in self.strategy_advisor.objectives:
        if isinstance(objective, DefenseObjective):
          await self._client.move_camera(objective.enemies.center)
          return

      # if we're building a new base
      if self.already_pending(UnitTypeId.NEXUS) > 0 and self.structures(UnitTypeId.NEXUS).not_ready.empty:
        await self._client.move_camera(self.economy_advisor.next_base_location)
        return

      # if we can see more than half their army
      if self.enemy_units.amount > self.enemy_army_size() / 2:
        await self._client.move_camera(self.enemy_units.center)
        return

      # if a scout sees something
      scouts = self.units.tags_in(self.tagged_units.scouting)
      if scouts.exists:
        interesting_scouts = scouts.filter(lambda scout:
          any(enemy.position.is_closer_than(8, scout)
            for enemy in self.enemy_units + self.enemy_structures
          )
        )

        if interesting_scouts.exists:
          await self._client.move_camera(interesting_scouts.first.position)
          return

      if self.structures.filter(lambda st: st.has_buff(BuffId.CHRONOBOOSTENERGYCOST) and st.buff_duration_remain > 50).exists:
        await self._client.move_camera(
          self.structures.filter(lambda st:
            st.has_buff(BuffId.CHRONOBOOSTENERGYCOST)
            and st.buff_duration_remain > 15
          ).first.position
        )
        return

      else:
        await self._client.move_camera(
          self.rally_point if self.rally_point and self.units.closer_than(10, self.rally_point).amount > 2
          else self.townhalls.first
        )

  async def on_step(self, iteration):
    for unrecognized_unit in self.enemy_units.filter(lambda u: u.type_id.name not in all_unit_ids):
      print(f"UNRECOGNIZED UNIT TYPE: {unrecognized_unit.type_id}")
    await self.chit_chat()
    await self.set_camera()
    requests = []
    self.desired_supply_buffer = 2 + self.structures({ UnitTypeId.WARPGATE, UnitTypeId.GATEWAY }).amount * 2.5
    for advisor in self.advisors:
      advisorResult = await advisor.tick()
      if advisorResult == None:
        print("exiting due to surrender")
        return
      requests.extend(advisorResult)

    requests.sort(key=urgencyValue, reverse=True)
    mineral_threshold = None
    vespene_threshold = None
    supply_threshold = None
    minerals = self.minerals
    vespene = self.vespene
    supply = self.supply_left
    while requests:
      request = requests.pop(0)
      if not request.urgency:
        break

      cost = self.calculate_cost(request.expense)
      supply_cost = self.calculate_supply_cost(request.expense) if isinstance(request.expense, UnitTypeId) else 0
      thresholds = ( mineral_threshold, vespene_threshold, supply_threshold )
      lowest_threshold = min(thresholds) if all(t != None for t in thresholds) else Urgency.NONE
      if request.urgency < lowest_threshold:
        break
      if cost.minerals and mineral_threshold and request.urgency < mineral_threshold:
        continue
      if cost.vespene and vespene_threshold and request.urgency < vespene_threshold:
        continue
      if supply_cost and supply_threshold and request.urgency < supply_threshold:
        continue

      can_afford = True
      if cost.minerals > minerals:
        can_afford = False
        mineral_threshold = request.urgency

      if cost.vespene > vespene:
        can_afford = False
        vespene_threshold = request.urgency

      if supply_cost > supply:
        can_afford = False
        supply_threshold = request.urgency

      if can_afford:
        minerals -= cost.minerals
        vespene -= cost.vespene
        supply -= supply_cost
        action = await request.fulfill(self)
        if action:
          self.do(action)

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

  def enemy_army_size(self):
    return len([ u for u in self.advisor_data.scouting['enemy_army'].values() if u.type_id not in [ UnitTypeId.PROBE, UnitTypeId.DRONE, UnitTypeId.SCV ] ])

  def enemy_army_dps(self):
    return sum([ max(u.ground_dps, u.air_dps) for u in self.advisor_data.scouting['enemy_army'].values() if u.ground_dps > 5 or u.air_dps > 0 ])

  def enemy_army_max_hp(self):
    return sum([ u.health_max + u.shield_max for u in self.advisor_data.scouting['enemy_army'].values() if u.ground_dps > 5 or u.air_dps > 0 ])

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
  "BelShirVestigeLE",
  "BlackpinkLE",
#  "BloodBoilLE", #-- fuck this map
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
    Computer(Race.Protoss, Difficulty.VeryHard, AIBuild.RandomBuild) # Macro, Power, Rush, Timing, Air, (RandomBuild)
  ], realtime=False)

if __name__ == '__main__':
  main()
