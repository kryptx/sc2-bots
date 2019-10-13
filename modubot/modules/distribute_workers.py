from sc2.constants import UnitTypeId, AbilityId
from sc2.units import Units

from modubot.common import list_flatten
from modubot.modules.module import BotModule

class WorkerDistributor(BotModule):
  def __init__(self, bot):
    super().__init__(bot)
    self.last_distribute = 0

  async def on_step(self, iteration):
    self.distribute_workers()

  def distribute_workers(self):
    # Only do anything once every 3 seconds
    if self.time - self.last_distribute < 3:
      return

    self.last_distribute = self.time

    # Kinda hard to gather anything without a nexus
    if not self.townhalls.ready.exists:
      return

    # mineral patches near one of our bases
    acceptable_minerals = self.mineral_field.filter(
      lambda node: any([
        nex.position.is_closer_than(15, node.position)
        for nex in self.townhalls.ready
      ])
    )

    workers_per_assimilator = 1 + min(2, int(self.workers.amount / acceptable_minerals.amount))

    # assimilators probably at bases that have been destroyed
    bad_assimilators = self.structures(
      UnitTypeId.ASSIMILATOR
    ).filter(
      lambda a: all(ex.is_further_than(15, a) for ex in self.owned_expansions.keys())
                or a.vespene_contents == 0
                or a.assigned_harvesters > workers_per_assimilator
    )

    # assimilators that don't have enough harvesters
    needy_assimilators = self.structures(
      UnitTypeId.ASSIMILATOR
    ).ready.tags_not_in([
      a.tag
      for a in bad_assimilators
    ]).filter(
      lambda a: a.assigned_harvesters < workers_per_assimilator
    )

    # tag collections for easy selection and matching
    acceptable_mineral_tags = [ f.tag for f in acceptable_minerals ]
    needy_mineral_tags = [
      f.tag
      for f in acceptable_minerals
      if self.townhalls.closest_to(f.position).surplus_harvesters < 0
    ]

    # anywhere else is strictly forbidden
    unacceptable_mineral_tags = [ f.tag for f in self.mineral_field.tags_not_in(acceptable_mineral_tags) ]

    bad_workers = self.unallocated(UnitTypeId.PROBE).filter(lambda p:
      # Grab these suckers first
      p.is_idle or
      (p.is_gathering and p.orders[0].target in unacceptable_mineral_tags) or
      (p.is_gathering and p.orders[0].target in bad_assimilators) or
      p.orders[0].ability in [ AbilityId.ATTACK_ATTACKTOWARDS,
                               AbilityId.ATTACK_ATTACK,
                               AbilityId.ATTACK ]
    )

    # up to N workers, where N is the number of surplus harvesters, from each nexus where there are any
    # may not grab them all every time (it gets only the ones returning minerals), but it'll get enough
    excess_workers = Units(list_flatten([
        self.workers.filter(
          lambda probe: probe.is_carrying_minerals and probe.orders and probe.orders[0].target == nex.tag
        )[0:nex.surplus_harvesters] for nex in self.townhalls.filter(lambda nex: nex.surplus_harvesters > 0)
    ]), self)

    # to fill up your first assimilator, you'll need these
    mining_workers = self.workers.filter(lambda p:
      # if more are needed, this is okay too
      p.is_gathering and (p.orders[0].target in acceptable_mineral_tags or p.is_carrying_minerals)
    ) - (bad_workers + excess_workers)

    usable_workers = bad_workers + excess_workers + mining_workers

    taken_workers = 0
    def get_workers(num):
      nonlocal taken_workers
      if taken_workers + num > usable_workers.amount:
        return []
      taken_workers += num
      return usable_workers[ taken_workers - num : taken_workers ]

    for needy_assimilator in needy_assimilators:
      workers = get_workers(workers_per_assimilator - needy_assimilator.assigned_harvesters)
      for worker in workers:
        self.do(worker.gather(needy_assimilator))

    if taken_workers < bad_workers.amount and acceptable_mineral_tags:
      remaining_bad_workers = get_workers(bad_workers.amount - taken_workers)
      for worker in remaining_bad_workers:
        self.do(worker.gather(self.mineral_field.tags_in(acceptable_mineral_tags).random))

    if taken_workers < bad_workers.amount + excess_workers.amount and needy_mineral_tags:
      remaining_excess_workers = get_workers(bad_workers.amount + excess_workers.amount - taken_workers)
      for worker in remaining_excess_workers:
        self.do(worker.gather(self.mineral_field.tags_in(needy_mineral_tags).random))
