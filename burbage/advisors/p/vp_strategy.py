import random

import sc2
from sc2.constants import *

from burbage.advisors.advisor import Advisor
from burbage.common import Urgency, TrainingRequest, StructureRequest, ResearchRequest, list_flatten

class PvPStrategyAdvisor(Advisor):
  def __init__(self, manager):
    super().__init__(manager)

  async def tick(self):
    requests = []
    await self.audit_battlefield(requests)
    self.handle_threats()
    self.scout()

    return requests

  def scout(self):
    if self.manager.units(UnitTypeId.OBSERVER).idle.exists:
      for phoenix in self.manager.units(UnitTypeId.OBSERVER).idle:
        scout_locations = list(self.manager.expansion_locations.keys()) + self.manager.enemy_start_locations
        target = scout_locations[random.randint(0, len(scout_locations) - 1)]
        self.manager.do(phoenix.move(target))

  def handle_threats(self):
    enemy_units = self.manager.enemy_units
    if enemy_units.empty:
      return
    threatening_units = list_flatten([enemy_units.closer_than(35, nex) for nex in self.manager.townhalls])
    available_defenders = self.manager.units({ UnitTypeId.ZEALOT, UnitTypeId.STALKER, UnitTypeId.ARCHON }).idle
    if threatening_units and available_defenders.exists:
      for defender in available_defenders:
        self.manager.do(defender.attack(threatening_units[random.randint(0, len(threatening_units) - 1)].position))

  async def build_stargate_units(self, stargates, requests):
    if any([not sg.orders for sg in stargates]):
      numPhoenixes = self.manager.units(PHOENIX).amount
      numPhoenixes += stargates.filter(lambda sg: sg.orders and sg.orders[0].ability == STARGATETRAIN_PHOENIX).amount
      for sg in stargates.filter(lambda sg: sg.is_idle):
        urgency = Urgency.MEDIUM
        if numPhoenixes < 1:
          urgency = Urgency.MEDIUMHIGH
        if numPhoenixes < 4:
          requests.append(TrainingRequest(PHOENIX, sg, urgency))

  async def build_robotics_units(self, robos, requests):
    if any([not robo.orders for robo in robos]):
      numObservers = self.manager.units(UnitTypeId.OBSERVER).amount
      numObservers += robos.filter(lambda r: r.orders and r.orders[0].ability == AbilityId.ROBOTICSFACILITYTRAIN_OBSERVER).amount
      for robo in robos.filter(lambda r: r.is_idle):
        urgency = Urgency.MEDIUM
        if numObservers < 1:
          urgency = Urgency.MEDIUMHIGH
        if numObservers < 2:
          requests.append(TrainingRequest(UnitTypeId.OBSERVER, robo, urgency))
          numObservers += 1

  async def build_gateway_units(self, requests):
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
      ZEALOT: AbilityId.WARPGATETRAIN_ZEALOT,
      STALKER: AbilityId.WARPGATETRAIN_STALKER,
      HIGHTEMPLAR: AbilityId.WARPGATETRAIN_HIGHTEMPLAR
    }

    if stalkers.idle.amount > 16:
      attack_location = self.manager.enemy_start_locations[0]
      for unit in self.manager.units({ ZEALOT, STALKER, ARCHON }):
        if self.manager.enemy_structures.exists:
          attack_location = self.manager.enemy_structures.random.position
        self.manager.do(unit.attack(attack_location))

    for warpgate in self.manager.structures(WARPGATE).ready:
      desired_unit = STALKER
      if counts[ZEALOT] < counts[STALKER]:
        desired_unit = ZEALOT
      if archives.exists and counts[ARCHON] < counts[STALKER] / 4:
        desired_unit = HIGHTEMPLAR

      if not self.manager.can_afford(desired_unit): # we're done here
        return

      abilities = await self.manager.get_available_abilities(warpgate)
      # all the units have the same cooldown anyway so let's just look at ZEALOT
      if AbilityId.WARPGATETRAIN_ZEALOT in abilities:
        pos = pylon.position.to2.random_on_distance([2, 5])
        placement = await self.manager.find_placement(warp_id[desired_unit], pos, placement_step=1)

        if not placement is None:
          self.manager.do(warpgate.warp_in(desired_unit, placement))

    gateways = self.manager.structures(GATEWAY)
    if gateways.idle.exists and not self.manager.structures(WARPGATE).exists:
      numStalkers = self.manager.units(STALKER).amount
      numStalkers += gateways.filter(lambda g: not g.is_idle and g.orders[0].ability == GATEWAYTRAIN_STALKER).amount
      if numStalkers < 24:
        for g in gateways.idle:
          desired_unit = STALKER
          if counts[ZEALOT] < counts[STALKER] / 2:
            desired_unit = ZEALOT
          requests.append(TrainingRequest(desired_unit, g, Urgency.MEDIUM))
    return

  async def audit_battlefield(self, requests):
    for templar in self.manager.units(HIGHTEMPLAR):
      self.manager.do(templar(AbilityId.MORPH_ARCHON))

    # Without pylons, we are nothing
    if not self.manager.structures(PYLON).ready.exists:
      return

    # Prep some collections
    gateways = self.manager.structures({ GATEWAY, WARPGATE })
    nexuses = self.manager.townhalls
    councils = self.manager.structures(TWILIGHTCOUNCIL)
    archives = self.manager.structures(TEMPLARARCHIVE)

    # TODO: Smarter building placement
    pylon = self.manager.structures(PYLON).ready.random

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

    for idle_forge in self.manager.structures(UnitTypeId.FORGE).idle:
      forge_abilities = await self.manager.get_available_abilities(idle_forge)
      if AbilityId.FORGERESEARCH_PROTOSSGROUNDWEAPONSLEVEL1 in forge_abilities:
        requests.append(ResearchRequest(AbilityId.FORGERESEARCH_PROTOSSGROUNDWEAPONSLEVEL1, idle_forge, Urgency.MEDIUM))
      elif AbilityId.FORGERESEARCH_PROTOSSGROUNDARMORLEVEL1 in forge_abilities:
        requests.append(ResearchRequest(AbilityId.FORGERESEARCH_PROTOSSGROUNDARMORLEVEL1, idle_forge, Urgency.MEDIUMLOW))
      elif AbilityId.FORGERESEARCH_PROTOSSGROUNDWEAPONSLEVEL2 in forge_abilities:
        requests.append(ResearchRequest(AbilityId.FORGERESEARCH_PROTOSSGROUNDWEAPONSLEVEL2, idle_forge, Urgency.MEDIUMLOW))
      elif AbilityId.FORGERESEARCH_PROTOSSGROUNDARMORLEVEL2 in forge_abilities:
        requests.append(ResearchRequest(AbilityId.FORGERESEARCH_PROTOSSGROUNDARMORLEVEL2, idle_forge, Urgency.MEDIUM))
      elif AbilityId.FORGERESEARCH_PROTOSSGROUNDWEAPONSLEVEL3 in forge_abilities:
        requests.append(ResearchRequest(AbilityId.FORGERESEARCH_PROTOSSGROUNDWEAPONSLEVEL3, idle_forge, Urgency.MEDIUMLOW))
      elif AbilityId.FORGERESEARCH_PROTOSSGROUNDARMORLEVEL3 in forge_abilities:
        requests.append(ResearchRequest(AbilityId.FORGERESEARCH_PROTOSSGROUNDARMORLEVEL3, idle_forge, Urgency.MEDIUMLOW))
      elif AbilityId.FORGERESEARCH_PROTOSSSHIELDSLEVEL1 in forge_abilities:
        requests.append(ResearchRequest(AbilityId.FORGERESEARCH_PROTOSSSHIELDSLEVEL1, idle_forge, Urgency.MEDIUMLOW))
      elif AbilityId.FORGERESEARCH_PROTOSSSHIELDSLEVEL2 in forge_abilities:
        requests.append(ResearchRequest(AbilityId.FORGERESEARCH_PROTOSSSHIELDSLEVEL2, idle_forge, Urgency.MEDIUMLOW))
      elif AbilityId.FORGERESEARCH_PROTOSSSHIELDSLEVEL3 in forge_abilities:
        requests.append(ResearchRequest(AbilityId.FORGERESEARCH_PROTOSSSHIELDSLEVEL3, idle_forge, Urgency.MEDIUMLOW))

    cores = self.manager.structures(CYBERNETICSCORE).ready
    if not cores.exists:
      return

    core = cores.first
    abilities = await self.manager.get_available_abilities(core)
    if AbilityId.RESEARCH_WARPGATE in abilities:
      requests.append(ResearchRequest(RESEARCH_WARPGATE, core, Urgency.HIGH))
    else:
      if core.orders and not core.has_buff(BuffId.CHRONOBOOSTENERGYCOST):
        for nexus in nexuses:
          abilities = await self.manager.get_available_abilities(nexus)
          if AbilityId.EFFECT_CHRONOBOOSTENERGYCOST in abilities:
            self.manager.do(nexus(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, core))
            break

    numGateways = gateways.amount
    if not self.manager.already_pending(GATEWAY) and (numGateways < self.manager.townhalls.amount * 2 or self.manager.minerals > 1500):
      requests.append(StructureRequest(GATEWAY, pylon.position, Urgency.MEDIUM))

    if numGateways > 0:
      await self.build_gateway_units(requests)

    if self.manager.structures(CYBERNETICSCORE).ready.exists:
      robos = self.manager.structures(UnitTypeId.ROBOTICSFACILITY)
      numRobos = robos.amount
      if numRobos == 0:
        requests.append(StructureRequest(UnitTypeId.ROBOTICSFACILITY, pylon.position, Urgency.MEDIUMHIGH))
      else:
        await self.build_robotics_units(robos, requests)

    if not councils.exists and not self.manager.already_pending(TWILIGHTCOUNCIL):
      requests.append(StructureRequest(TWILIGHTCOUNCIL, pylon.position, Urgency.MEDIUMHIGH))

    if councils.idle.exists:
      council = councils.idle.first
      tc_abilities = await self.manager.get_available_abilities(council)
      if AbilityId.RESEARCH_CHARGE in tc_abilities:
        requests.append(ResearchRequest(RESEARCH_CHARGE, council, Urgency.MEDIUMHIGH))

    if not councils.exists:
      return

    if not archives.exists and not self.manager.already_pending(TEMPLARARCHIVE):
      requests.append(StructureRequest(TEMPLARARCHIVE, pylon.position, Urgency.MEDIUMHIGH))