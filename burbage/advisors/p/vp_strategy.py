import random

import sc2
from sc2.constants import *

from burbage.advisors.advisor import Advisor
from burbage.common import Urgency, TrainingRequest, StructureRequest, ResearchRequest, list_flatten

class PvPStrategyAdvisor(Advisor):
  def __init__(self, manager):
    super().__init__(manager)
    self.warpgate_complete = False

  async def on_upgrade_complete(self, upgrade):
    if upgrade == UpgradeId.WARPGATERESEARCH:
      self.warpgate_complete = True

  async def tick(self):
    requests = []
    self.manager.rally_point = self.determine_rally_point()
    await self.audit_structures(requests)
    await self.audit_research(requests)
    await self.build_gateway_units(requests)
    await self.build_robotics_units(requests)
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

  def allocate_units(self):
    # Populate values for tactical advisor to read
    my_army = self.manager.units({ UnitTypeId.ZEALOT, UnitTypeId.STALKER, UnitTypeId.ARCHON })
    if my_army.idle.amount >= 35:
      self.manager.attacker_tags = {
        u.tag
        for u in self.manager.units({ UnitTypeId.ZEALOT, UnitTypeId.STALKER, UnitTypeId.ARCHON })
      }
    else:
      self.manager.attacker_tags = []

    self.manager.scout_tags = {
      u.tag
      for u in self.manager.units(UnitTypeId.OBSERVER)
    }

    # Morph any archons
    for templar in self.manager.units(UnitTypeId.HIGHTEMPLAR):
      self.manager.do(templar(AbilityId.MORPH_ARCHON))

  def handle_threats(self):
    enemy_units = self.manager.enemy_units
    if enemy_units.empty:
      return
    threatening_units = list_flatten([enemy_units.closer_than(35, nex) for nex in self.manager.townhalls])
    available_defenders = self.manager.units({ UnitTypeId.ZEALOT, UnitTypeId.STALKER, UnitTypeId.ARCHON }).idle
    if threatening_units and available_defenders.exists:
      for defender in available_defenders:
        self.manager.do(defender.attack(threatening_units[random.randint(0, len(threatening_units) - 1)].position))

  async def build_robotics_units(self, requests):
    robos = self.manager.structures(UnitTypeId.ROBOTICSFACILITY)
    if robos.empty:
      return

    numObservers = self.manager.units(UnitTypeId.OBSERVER).amount

    for robo in robos.idle:
      urgency = Urgency.MEDIUM
      if numObservers < 1:
        urgency = Urgency.MEDIUMHIGH
      if numObservers < 2:
        requests.append(TrainingRequest(UnitTypeId.OBSERVER, robo, urgency))
        numObservers += 1

  async def build_gateway_units(self, requests):
    if self.manager.structures({ UnitTypeId.GATEWAY, UnitTypeId.WARPGATE }).empty:
      return

    pylon = self.manager.structures(UnitTypeId.PYLON).ready.closest_to(self.manager.game_info.map_center)
    zealots = self.manager.units(UnitTypeId.ZEALOT)
    stalkers = self.manager.units(UnitTypeId.STALKER)
    archons = self.manager.units(UnitTypeId.ARCHON)
    archives = self.manager.structures(UnitTypeId.TEMPLARARCHIVE)

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
      desired_unit = UnitTypeId.STALKER
      if counts[UnitTypeId.ZEALOT] < counts[UnitTypeId.STALKER] or not self.manager.can_afford(desired_unit):
        desired_unit = UnitTypeId.ZEALOT
      if archives.exists and (counts[UnitTypeId.ARCHON] < counts[UnitTypeId.STALKER] / 4 or not self.manager.can_afford(desired_unit)):
        desired_unit = UnitTypeId.HIGHTEMPLAR

      if not self.manager.can_afford(desired_unit): # we're done here
        return

      abilities = await self.manager.get_available_abilities(warpgate)
      # all the units have the same cooldown anyway so let's just look at ZEALOT
      if AbilityId.WARPGATETRAIN_ZEALOT in abilities:
        pos = pylon.position.to2.random_on_distance([2, 5])
        placement = await self.manager.find_placement(warp_id[desired_unit], pos, placement_step=1)

        if not placement is None:
          self.manager.do(warpgate.warp_in(desired_unit, placement))

    gateways = self.manager.structures(UnitTypeId.GATEWAY)
    if gateways.idle.exists and not self.warpgate_complete:
      for g in gateways.idle:
        desired_unit = UnitTypeId.STALKER
        if counts[UnitTypeId.ZEALOT] < counts[UnitTypeId.STALKER] / 2:
          desired_unit = UnitTypeId.ZEALOT
        requests.append(TrainingRequest(desired_unit, g, Urgency.HIGH))
    return

  def determine_rally_point(self):
    if self.manager.townhalls.empty or self.manager.townhalls.amount == 1:
      return self.manager.main_base_ramp.top_center

    base = self.manager.townhalls.closest_to(self.manager.game_info.map_center)
    def distance_to_base(ramp):
      return ramp.top_center.distance_to(base.position.towards(self.manager.game_info.map_center, 10))

    ramps = sorted(self.manager.game_info.map_ramps, key=distance_to_base)
    return ramps[0].top_center

  async def audit_research(self, requests):
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
      return

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

  async def audit_structures(self, requests):
    # Without pylons, can't do much more
    if not self.manager.structures(UnitTypeId.PYLON).ready.exists:
      return

    # Prep some collections
    gateways = self.manager.structures({ UnitTypeId.GATEWAY, UnitTypeId.WARPGATE })
    nexuses = self.manager.townhalls
    councils = self.manager.structures(UnitTypeId.TWILIGHTCOUNCIL)
    archives = self.manager.structures(UnitTypeId.TEMPLARARCHIVE)

    # TODO: Smarter building placement
    pylon = self.manager.structures(UnitTypeId.PYLON).ready.random

    # The rest of this is just tech tree stuff. gateway > core > forge + robo + TC > TA
    # Gateways before all. we're not cannon rushing.
    if not gateways.exists:
      requests.append(StructureRequest(UnitTypeId.GATEWAY, pylon.position, Urgency.HIGH))
      return

    if (not self.manager.structures(UnitTypeId.CYBERNETICSCORE).exists
    and not self.manager.already_pending(UnitTypeId.CYBERNETICSCORE)
    and gateways.ready.exists):
      requests.append(StructureRequest(UnitTypeId.CYBERNETICSCORE, pylon.position, Urgency.HIGH))

    # forge when you get around to it.
    if (self.manager.units({ UnitTypeId.ZEALOT, UnitTypeId.STALKER, UnitTypeId.ARCHON }).amount >= 5
    and not self.manager.structures(UnitTypeId.FORGE).exists
    and not self.manager.already_pending(UnitTypeId.FORGE)):
      requests.append(StructureRequest(UnitTypeId.FORGE, pylon.position, Urgency.MEDIUMLOW))

    cores = self.manager.structures(UnitTypeId.CYBERNETICSCORE).ready
    if not cores.exists:
      return

    numGateways = gateways.amount
    if not self.manager.already_pending(UnitTypeId.GATEWAY) and (numGateways < self.manager.townhalls.amount * 2 or self.manager.minerals > 1500):
      requests.append(StructureRequest(UnitTypeId.GATEWAY, pylon.position, Urgency.MEDIUM))

    # BUILD A ROBO
    if self.manager.structures(UnitTypeId.ROBOTICSFACILITY).empty:
      requests.append(StructureRequest(UnitTypeId.ROBOTICSFACILITY, pylon.position, Urgency.MEDIUMHIGH))

    # BUILD A COUNCIL
    if not councils.exists and not self.manager.already_pending(UnitTypeId.TWILIGHTCOUNCIL):
      requests.append(StructureRequest(UnitTypeId.TWILIGHTCOUNCIL, pylon.position, Urgency.MEDIUMHIGH))

    # RESEARCH CHARGE
    if councils.idle.exists:
      council = councils.idle.first
      tc_abilities = await self.manager.get_available_abilities(council)
      if AbilityId.RESEARCH_CHARGE in tc_abilities:
        requests.append(ResearchRequest(AbilityId.RESEARCH_CHARGE, council, Urgency.MEDIUMHIGH))

    if not councils.exists:
      return

    # BUILD AN ARCHIVE
    if not archives.exists and not self.manager.already_pending(UnitTypeId.TEMPLARARCHIVE):
      requests.append(StructureRequest(UnitTypeId.TEMPLARARCHIVE, pylon.position, Urgency.MEDIUMHIGH))