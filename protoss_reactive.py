from sc2.constants import UnitTypeId, BuffId, UpgradeId

from modubot.bot import ModuBot
from modubot.common import Urgency
from modubot.modules import *
from modubot.scouting import *
from modubot.objectives.objective import ObjectiveStatus

def army_priority(bot):
  def unit_amount(unit_id):
    if unit_id == UnitTypeId.HIGHTEMPLAR:
      return bot.units(unit_id).amount + bot.units(UnitTypeId.ARCHON).amount / 2
    else:
      return bot.units(unit_id).amount

  def calculate_priorities():
    priority = [ UnitTypeId.STALKER ]
    if getattr(bot.shared, 'warpgate_complete', False) or bot.townhalls.amount > 1 or bot.vespene > 500:
      priority = sorted([ UnitTypeId.HIGHTEMPLAR, UnitTypeId.STALKER  ], key=unit_amount)

    priority.append(UnitTypeId.ZEALOT)
    bot.log.info(f"Returning unit priority {priority}")
    return priority

  return calculate_priorities

def shield_is_not_full(unit):
  return unit.shield < unit.shield_max * 0.95

def build():
  bot = ModuBot(limits={
      UnitTypeId.FORGE: 1,
      UnitTypeId.CYBERNETICSCORE: 1,
      UnitTypeId.ROBOTICSBAY: 1,
      UnitTypeId.ROBOTICSFACILITY: 1,
      UnitTypeId.TWILIGHTCOUNCIL: 1,
      UnitTypeId.TEMPLARARCHIVE: 1,
      UnitTypeId.GATEWAY: 3
  })

  bot.modules = [
      GameStateTracker(bot),
      OptimismChatter(bot),
      SpectatorCamera(bot),
      WorkerDistributor(bot),
      AttackBases(bot),
      DefendBases(bot),
      ProtossMicro(bot),
      RallyPointer(bot),
      ArchonMaker(bot, max_energy=300),
      SupplyBufferer(bot),
      MacroManager(bot),
      ChronoBooster(bot,
        find_structure=lambda: (
          bot.structures(UnitTypeId.FORGE).filter(lambda f: not f.is_idle).first
            if bot.structures(UnitTypeId.FORGE).filter(lambda f: not f.is_idle).exists
          else bot.structures(UnitTypeId.NEXUS).filter(lambda n: not n.is_idle).first
            if (bot.structures(UnitTypeId.NEXUS).filter(lambda n: not n.is_idle).exists and bot.supply_left > 2 and bot.workers.amount < 70)
          else bot.structures({ UnitTypeId.WARPGATE }).filter(lambda gate: not gate.has_buff(BuffId.CHRONOBOOSTENERGYCOST)).random
            if bot.structures({ UnitTypeId.WARPGATE }).filter(lambda gate: not gate.has_buff(BuffId.CHRONOBOOSTENERGYCOST)).exists
            and bot.townhalls.filter(lambda nex: nex.energy > 190).exists
          else None
        )
      ),
      ScoutManager(bot,
        missions=[
          FindBasesMission(bot,
            unit_priority=[ UnitTypeId.OBSERVER, UnitTypeId.ADEPT, UnitTypeId.PROBE ],
            retreat_while=shield_is_not_full),
          DetectCheeseMission(bot,
            unit_priority=[ UnitTypeId.PROBE ],
            retreat_while=shield_is_not_full),
          ExpansionHuntMission(bot,
            unit_priority=[ UnitTypeId.OBSERVER, UnitTypeId.ADEPT ],
            retreat_while=shield_is_not_full),
          WatchEnemyArmyMission(bot,
            unit_priority=[ UnitTypeId.ADEPT, UnitTypeId.ZEALOT, UnitTypeId.PROBE ],
            retreat_while=shield_is_not_full),
          WatchEnemyArmyMission(bot,
            unit_priority=[ UnitTypeId.OBSERVER ],
            retreat_while=shield_is_not_full),
          WatchEnemyArmyMission(bot,
            unit_priority=[ UnitTypeId.ADEPTPHASESHIFT ],
            retreat_while=shield_is_not_full),
          SupportArmyMission(bot,
            unit_priority=[ UnitTypeId.OBSERVER ],
            retreat_while=shield_is_not_full)
        ]),
      SimpleArmyBuilder(bot, get_priorities=army_priority(bot)),
      Upgrader(bot,
        upgrade_sets={
          Urgency.HIGH: [
            [ UpgradeId.WARPGATERESEARCH ]
          ],
          Urgency.MEDIUMLOW: [
            [ UpgradeId.PROTOSSGROUNDWEAPONSLEVEL1,
              UpgradeId.PROTOSSGROUNDARMORSLEVEL1,
              UpgradeId.PROTOSSGROUNDWEAPONSLEVEL2,
              UpgradeId.PROTOSSGROUNDARMORSLEVEL2,
              UpgradeId.PROTOSSSHIELDSLEVEL1,
              UpgradeId.PROTOSSGROUNDWEAPONSLEVEL3,
              UpgradeId.PROTOSSGROUNDARMORSLEVEL3,
              UpgradeId.PROTOSSSHIELDSLEVEL2,
              UpgradeId.PROTOSSSHIELDSLEVEL3 ],
            [ UpgradeId.BLINKTECH, UpgradeId.CHARGE ]
          ],
          Urgency.LOW: [
            [ UpgradeId.OBSERVERGRAVITICBOOSTER ]
          ]
        }
      )
    ]

  return bot
