import random
import math

import sc2
from sc2.constants import *
from sc2.units import Units

from burbage.advisors.advisor import Advisor
from burbage.common import Urgency, TrainingRequest, WarpInRequest, StructureRequest, ResearchRequest, list_flatten

BASE_DEFENSE_RADIUS = 35

class DefenseMission():
  def __init__(self, target):
    self.last_visible = 0
    self.target = target
    self.defenders = []
    self.desired_unit_quantity = 2
    self.enemy_killed = False

  def is_complete(self, now, bases):
    return self.enemy_killed or now - self.last_visible > 10 or all(base.position.is_further_than(BASE_DEFENSE_RADIUS, self.target.position) for base in bases)

class PvPStrategyAdvisor(Advisor):
  def __init__(self, manager):
    super().__init__(manager)
    self.warpgate_complete = False
    self.defense = dict() # enemy_tag: DefenseMission
    self.last_defense_check = dict() # enemy tag: time

  @property
  def defenders(self):
    return list_flatten([ mission.defenders for mission in self.defense.values() ])

  async def on_upgrade_complete(self, upgrade):
    if upgrade == UpgradeId.WARPGATERESEARCH:
      self.warpgate_complete = True

  async def on_unit_destroyed(self, unit):
    if unit in self.defense:
      self.defense[unit].enemy_killed = True
    else:
      for mission in self.defense.values():
        if unit in mission.defenders:
          mission.defenders.remove(unit)
          break

  async def tick(self):
    self.manager.rally_point = self.determine_rally_point()
    requests = self.audit_structures()
    requests += await self.audit_research()
    requests += await self.build_gateway_units()
    self.use_excess_chrono_boosts()
    self.handle_threats()
    self.allocate_units()
    return requests

  def use_excess_chrono_boosts(self):
    full_nexuses = self.manager.townhalls.filter(lambda nex: nex.energy > 190)
    if full_nexuses.exists:
      nexus = full_nexuses.random
      gate = self.manager.structures({
        UnitTypeId.GATEWAY,
        UnitTypeId.WARPGATE
      }).filter(lambda gate: not gate.has_buff(BuffId.CHRONOBOOSTENERGYCOST))

      if gate.exists:
        self.manager.do(nexus(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, gate.random))

  def assign_defenders(self, unit):
    if unit.tag in self.last_defense_check and self.manager.time - self.last_defense_check[unit.tag] < 2:
      return
    self.last_defense_check[unit.tag] = self.manager.time
    mission = self.defense[unit.tag] if unit.tag in self.defense else DefenseMission(unit)
    self.defense[unit.tag] = mission

    mission.last_visible = self.manager.time
    current_defenders = self.manager.units.tags_in([ d.tag for d in mission.defenders ])

    if current_defenders.amount >= mission.desired_unit_quantity:
      return

    ## DID YOU GET AN ERROR ABOUT AN EMPTY UNITS OBJECT?
    # The python -O option will ignore the assert. it's perfectly safe.
    existing_defenders = [ d.tag for d in self.defenders ]
    stalkers = self.manager.units({ UnitTypeId.STALKER }).tags_not_in(existing_defenders).closest_n_units(unit.position, 2)
    archons = self.manager.units({ UnitTypeId.ARCHON }).tags_not_in(existing_defenders).closest_n_units(unit.position, 2)
    zealots = self.manager.units({ UnitTypeId.ZEALOT }).tags_not_in(existing_defenders).closest_n_units(unit.position, 2)
    defenders = stalkers + archons + zealots  # ordered

    #print("mission " + str(unit.tag) + " defenders size is now " + str(len(mission.defenders)))
    #print("mission " + str(unit.tag) + " has desired quantity of " + str(mission.desired_unit_quantity))
    needed_quantity = mission.desired_unit_quantity - current_defenders.amount
    #print("mission " + str(unit.tag) + " needs " + str(needed_quantity) + " more defenders")
    mission.defenders.extend(defenders[:needed_quantity])
    #print("mission " + str(unit.tag) + " defenders size is now " + str(len(mission.defenders)))

  def allocate_units(self):
    # Populate values for tactical advisor to read
    my_army = self.manager.units({
      UnitTypeId.ZEALOT,
      UnitTypeId.STALKER,
      UnitTypeId.ARCHON
    }).tags_not_in(self.manager.tagged_units.scouting)

    if my_army.idle.amount >= 35:
      self.manager.tagged_units.strategy = set(
        u.tag
        for u in self.manager.units({ UnitTypeId.ZEALOT, UnitTypeId.STALKER, UnitTypeId.ARCHON })
      )
    else:
      self.manager.tagged_units.strategy = set()

    # Morph any archons
    for templar in self.manager.units(UnitTypeId.HIGHTEMPLAR):
      self.manager.do(templar(AbilityId.MORPH_ARCHON))

  def handle_threats(self):
    threats = list_flatten([self.manager.enemy_units.closer_than(30, nex) for nex in self.manager.townhalls])
    for threat in threats:
      self.assign_defenders(threat)

    now = self.manager.time
    for enemy in list(self.defense.keys()):
      if self.defense[enemy].is_complete(now, self.manager.townhalls):
        del self.defense[enemy]

  def army_dps(self):
    return sum([ max(u.ground_dps, u.air_dps) for u in self.manager.units if u.ground_dps > 5 or u.air_dps > 0 ])

  def army_max_hp(self):
    return sum([ u.health_max + u.shield_max for u in self.manager.units if u.ground_dps > 5 or u.air_dps > 0 ])

  def fuckedness_ratio(self):
    return (self.manager.scouting_advisor.enemy_army_dps() * self.manager.scouting_advisor.enemy_army_max_hp() + 100) / (self.army_dps() * self.army_max_hp() + 100)

  async def build_gateway_units(self):
    requests = []
    if self.manager.structures({ UnitTypeId.GATEWAY, UnitTypeId.WARPGATE }).empty:
      return requests

    pylon = self.manager.structures(UnitTypeId.PYLON).ready.closest_to(self.manager.game_info.map_center)
    zealots = self.manager.units(UnitTypeId.ZEALOT)
    stalkers = self.manager.units(UnitTypeId.STALKER)
    archons = self.manager.units(UnitTypeId.ARCHON)
    archives = self.manager.structures(UnitTypeId.TEMPLARARCHIVE)
    army_priority = 0
    if self.manager.time < 240 and self.manager.advisor_data.scouting['enemy_is_rushing']:
      army_priority += 2

    # Veryhigh is still only 2 (LOW) away from LIFEORDEATH
    # i.e. even if no cheese it only takes a ratio of 3 to be in a life or death urgency situation (will cut probes)
    army_priority += min(Urgency.VERYHIGH, max(0, math.floor(self.fuckedness_ratio() * 4)))
    urgency = Urgency.LOW + army_priority

    counts = {
      UnitTypeId.ZEALOT: zealots.amount,
      UnitTypeId.STALKER: stalkers.amount,
      UnitTypeId.ARCHON: archons.amount
    }

    warp_id = {
      UnitTypeId.ZEALOT: AbilityId.WARPGATETRAIN_ZEALOT,
      UnitTypeId.STALKER: AbilityId.WARPGATETRAIN_STALKER,
      UnitTypeId.HIGHTEMPLAR: AbilityId.WARPGATETRAIN_HIGHTEMPLAR
    }

    for warpgate in self.manager.structures(UnitTypeId.WARPGATE).ready:
      unit_priority = [ UnitTypeId.STALKER ]
      if counts[UnitTypeId.ZEALOT] < counts[UnitTypeId.STALKER]:
        unit_priority.insert(0, UnitTypeId.ZEALOT)

      if archives.exists:
        unit_priority.insert(0, UnitTypeId.HIGHTEMPLAR)

      desired_unit = next((unit for unit in unit_priority if self.manager.can_afford(unit)), None)

      if not desired_unit: # we're done here
        return requests

      abilities = await self.manager.get_available_abilities(warpgate)
      if AbilityId.WARPGATETRAIN_ZEALOT in abilities:
        pos = pylon.position.to2.random_on_distance([2, 5])
        placement = await self.manager.find_placement(warp_id[desired_unit], pos, placement_step=1)

        if not placement is None:
          requests.append(WarpInRequest(desired_unit, warpgate, placement, urgency))

    gateways = self.manager.structures(UnitTypeId.GATEWAY)

    if gateways.idle.exists and not self.warpgate_complete:
      for g in gateways.idle:
        desired_unit = UnitTypeId.STALKER
        if counts[UnitTypeId.ZEALOT] < counts[UnitTypeId.STALKER] or self.manager.vespene < 50:
          desired_unit = UnitTypeId.ZEALOT
        requests.append(TrainingRequest(desired_unit, g, urgency))

    return requests

  def determine_rally_point(self):
    if self.manager.townhalls.empty or self.manager.townhalls.amount == 1:
      return list(self.manager.main_base_ramp.upper)[0]

    base = self.manager.townhalls.closest_to(self.manager.game_info.map_center)
    def distance_to_base(ramp):
      return ramp.top_center.distance_to(base.position.towards(self.manager.game_info.map_center, 10))

    ramps = sorted(self.manager.game_info.map_ramps, key=distance_to_base)
    return list(ramps[0].upper)[0]

  async def audit_research(self):
    requests = []
    # FORGE UPGRADES
    for idle_forge in self.manager.structures(UnitTypeId.FORGE).idle:
      forge_abilities = await self.manager.get_available_abilities(idle_forge)
      if AbilityId.FORGERESEARCH_PROTOSSGROUNDWEAPONSLEVEL1 in forge_abilities:
        requests.append(ResearchRequest(AbilityId.FORGERESEARCH_PROTOSSGROUNDWEAPONSLEVEL1, idle_forge, Urgency.MEDIUM))
      elif AbilityId.FORGERESEARCH_PROTOSSGROUNDARMORLEVEL1 in forge_abilities:
        requests.append(ResearchRequest(AbilityId.FORGERESEARCH_PROTOSSGROUNDARMORLEVEL1, idle_forge, Urgency.MEDIUM))
      elif AbilityId.FORGERESEARCH_PROTOSSGROUNDWEAPONSLEVEL2 in forge_abilities:
        requests.append(ResearchRequest(AbilityId.FORGERESEARCH_PROTOSSGROUNDWEAPONSLEVEL2, idle_forge, Urgency.MEDIUM))
      elif AbilityId.FORGERESEARCH_PROTOSSGROUNDARMORLEVEL2 in forge_abilities:
        requests.append(ResearchRequest(AbilityId.FORGERESEARCH_PROTOSSGROUNDARMORLEVEL2, idle_forge, Urgency.MEDIUM))
      elif AbilityId.FORGERESEARCH_PROTOSSSHIELDSLEVEL1 in forge_abilities:
        requests.append(ResearchRequest(AbilityId.FORGERESEARCH_PROTOSSSHIELDSLEVEL1, idle_forge, Urgency.MEDIUMLOW))
      elif AbilityId.FORGERESEARCH_PROTOSSGROUNDWEAPONSLEVEL3 in forge_abilities:
        requests.append(ResearchRequest(AbilityId.FORGERESEARCH_PROTOSSGROUNDWEAPONSLEVEL3, idle_forge, Urgency.MEDIUMLOW))
      elif AbilityId.FORGERESEARCH_PROTOSSGROUNDARMORLEVEL3 in forge_abilities:
        requests.append(ResearchRequest(AbilityId.FORGERESEARCH_PROTOSSGROUNDARMORLEVEL3, idle_forge, Urgency.MEDIUMLOW))
      elif AbilityId.FORGERESEARCH_PROTOSSSHIELDSLEVEL2 in forge_abilities:
        requests.append(ResearchRequest(AbilityId.FORGERESEARCH_PROTOSSSHIELDSLEVEL2, idle_forge, Urgency.LOW))
      elif AbilityId.FORGERESEARCH_PROTOSSSHIELDSLEVEL3 in forge_abilities:
        requests.append(ResearchRequest(AbilityId.FORGERESEARCH_PROTOSSSHIELDSLEVEL3, idle_forge, Urgency.LOW))

    if self.warpgate_complete:
      for busy_forge in self.manager.structures(UnitTypeId.FORGE).filter(lambda f: not f.is_idle and not f.has_buff(BuffId.CHRONOBOOSTENERGYCOST)):
        for nexus in self.manager.townhalls:
          abilities = await self.manager.get_available_abilities(nexus)
          if AbilityId.EFFECT_CHRONOBOOSTENERGYCOST in abilities:
            self.manager.do(nexus(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, busy_forge))
            break

    cores = self.manager.structures(UnitTypeId.CYBERNETICSCORE)
    if cores.empty:
      return requests

    # CORE UPGRADES
    if cores.idle.exists:
      core = cores.idle.first
      abilities = await self.manager.get_available_abilities(core)
      if AbilityId.RESEARCH_WARPGATE in abilities:
        requests.append(ResearchRequest(AbilityId.RESEARCH_WARPGATE, core, Urgency.HIGH))
    else:
      core = cores.first
      if core.orders and not core.has_buff(BuffId.CHRONOBOOSTENERGYCOST):
        for nexus in self.manager.townhalls:
          abilities = await self.manager.get_available_abilities(nexus)
          if AbilityId.EFFECT_CHRONOBOOSTENERGYCOST in abilities:
            self.manager.do(nexus(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, core))
            break

    councils = self.manager.structures(UnitTypeId.TWILIGHTCOUNCIL)
    # COUNCIL
    if councils.idle.exists:
      council = councils.idle.first
      tc_abilities = await self.manager.get_available_abilities(council)
      if AbilityId.RESEARCH_CHARGE in tc_abilities:
        requests.append(ResearchRequest(AbilityId.RESEARCH_CHARGE, council, Urgency.MEDIUMHIGH))

    bays = self.manager.structures(UnitTypeId.ROBOTICSBAY)
    if bays.idle.exists:
      bay = bays.idle.first
      rb_abilities = await self.manager.get_available_abilities(bay)
      if AbilityId.RESEARCH_GRAVITICBOOSTER in rb_abilities:
        requests.append(ResearchRequest(AbilityId.RESEARCH_GRAVITICBOOSTER, bay, Urgency.LOW))

    return requests

  def audit_structures(self):
    requests = []
    # Without pylons, can't do much more
    if not self.manager.structures(UnitTypeId.PYLON).ready.exists:
      return requests

    # Prep some collections
    gateways = self.manager.structures({ UnitTypeId.GATEWAY, UnitTypeId.WARPGATE })
    councils = self.manager.structures(UnitTypeId.TWILIGHTCOUNCIL)
    archives = self.manager.structures(UnitTypeId.TEMPLARARCHIVE)

    # The rest of this is just tech tree stuff. gateway > core > forge + robo + TC > TA
    # Gateways before all. we're not cannon rushing.
    if not gateways.exists:
      requests.append(StructureRequest(UnitTypeId.GATEWAY, self.manager.planner, Urgency.VERYHIGH))
      return requests

    if (not self.manager.structures(UnitTypeId.CYBERNETICSCORE).exists
    and not self.manager.already_pending(UnitTypeId.CYBERNETICSCORE)
    and gateways.ready.exists):
      requests.append(StructureRequest(UnitTypeId.CYBERNETICSCORE, self.manager.planner, Urgency.HIGH))

    # forge when you get around to it.
    if (self.manager.units({ UnitTypeId.ZEALOT, UnitTypeId.STALKER, UnitTypeId.ARCHON }).amount >= 5
    and not self.manager.structures(UnitTypeId.FORGE).exists
    and not self.manager.already_pending(UnitTypeId.FORGE)):
      requests.append(StructureRequest(UnitTypeId.FORGE, self.manager.planner, Urgency.MEDIUMLOW))

    numGateways = gateways.amount
    if not self.manager.already_pending(UnitTypeId.GATEWAY) and (numGateways < self.manager.townhalls.amount * 2 or self.manager.minerals > 1500):
      requests.append(StructureRequest(UnitTypeId.GATEWAY, self.manager.planner, Urgency.HIGH))

    cores = self.manager.structures(UnitTypeId.CYBERNETICSCORE).ready
    if not cores.exists:
      return requests

    # BUILD A COUNCIL
    if not councils.exists and not self.manager.already_pending(UnitTypeId.TWILIGHTCOUNCIL):
      requests.append(StructureRequest(UnitTypeId.TWILIGHTCOUNCIL, self.manager.planner, Urgency.MEDIUMHIGH))

    if not councils.ready.exists:
      return requests

    # BUILD AN ARCHIVE
    if not archives.exists and not self.manager.already_pending(UnitTypeId.TEMPLARARCHIVE):
      requests.append(StructureRequest(UnitTypeId.TEMPLARARCHIVE, self.manager.planner, Urgency.MEDIUMHIGH))

    return requests