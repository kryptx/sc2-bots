import itertools
import logging
import math
import random

import sc2
from sc2 import Race, Difficulty
from sc2.player import Bot, Computer
from sc2.data import AIBuild

from maps import all_maps
from protoss_reactive import build as build_bot

bot = build_bot()

def main():
  sc2.run_game(sc2.maps.get(random.choice(all_maps)), [
    Bot(Race.Protoss, bot),
    Computer(Race.Protoss, Difficulty.VeryHard, AIBuild.RandomBuild) # Macro, Power, Rush, Timing, Air, (RandomBuild)
  ], realtime=False)

if __name__ == '__main__':
  main()
