#!/usr/bin/env python3

"""Autocaster, flexible mode: Given a model of what roles in your game
have which features, and a csv of app information (say, collected from
Google Forms), find and show a *pretty good* matching of apps to roles.

On a Mac about 2017, use Homebrew to `brew install python3; brew
install z3 --with-python3`.  Presumably python3 becomes standard at
some point.  Try first on the enclosed .csv file, which should take
about FIXME minutes to run.

Then you'll need to adjust runs and cols, bias and target, add a model
of your characters, and collect your apps.  If you have problems,
please call!

It can often be much, much faster to find a good-enough solution by
binary search than by insisting on an optimal solution.  Yes, this
should be automated---patches welcome.  Until then, start with a low
target.  Run the caster.  If it fails, you're game's uncastable!  If
it succeeds, double the target and run again.  Repeat until it fails
or takes a while.  If it's taking long enough for you to get bored,
now you can do binary search to find the highest target that will
succeed quickly.

Copyright 2017 Brian Sniffen.  See LICENSE.
"""

import csv
import sys
from z3 import *
from operator import itemgetter
from functools import reduce

debug=False

target = 132

bias = 3

runs = ["sunEve"] # "friEve satAft satEve sunAft sunEve".split()

cols = "timestamp name email first days mommy good bad priest sorcerer criminal innocent male female alien bastard blind diplomat spy liar kid fugitive soldier bountyHunter slaver slave racist traitor student noble bodyguard arrogant fearful disguise romance killed killer alone group lead follow".split()

# ** TODO check that names in characters match names in cols

rawCharacters = {
    "zeus":     ["bastard", "spy", "liar", "slave", "traitor", "fearful", "alone"],
    "hera":     ["good", "innocent", "bastard", "student", "follow"],
    "athena":     ["good", "soldier", "bastard", "lead"],
    "hephaestus":     ["male", "fugitive", "soldier", "disguise", "alone"],
    "artemis":    ["good", "soldier", "killer", "lead", "diplomat", "group"],
    "apollo":     ["bad", "soldier", "killer", "follow", "racist", "group"],
    "odin":    ["bad", "soldier", "killer", "follow", "racist", "group"],
    "thor":    ["good", "spy", "disguise", "killer", "alone"],
    "loki":  ["good", "priest", "male", "blind", "fugitive", "disguise", "lead", "killed", "killer", "group"],
    "hestia":  ["priest", "female", "student", "fugitive", "fearful", "romance", "killed", "follow", "group", "disguise"],
    "dionysus":      ["priest", "liar", "fugitive", "traitor", "disguise", "alone", "killer", "killed", "experienced"],
    "hades":      ["bad", "sorcerer", "traitor", "arrogant", "romance", "killer", "killed", "follow", "group", "male"],
    "poseidon":   ["bad", "sorcerer", "arrogant", "killer", "killed", "lead", "group", "experienced"],
    "frig":   ["good", "priest", "female", "fugitive", "disguise", "killed", "killer", "alone", "lead"],
    "freya": ["good", "noble", "innocent", "female", "kid", "student", "disguise", "romance", "group"],
    "hugin":    ["good", "bodyguard", "disguise", "killer", "group"],
    "munin":     ["male", "noble", "diplomat", "lead", "romance"],
    "monkeyking":    ["soldier", "bodyguard", "follow"],
    "pharoah":       ["criminal", "alien", "diplomat", "alone"],
    "caesar":       ["criminal", "alien", "diplomat", "alone", "arrogant"],
    "arthur":     ["liar", "bountyHunter", "slaver", "disguise", "killer", "killed", "alone"],
    "tsar":  ["bad", "criminal", "fugitive", "fearful", "alone"]
}

def expandCharacters(rawCharacters=rawCharacters,runs=runs):
    characters={}
    for char in rawCharacters.keys():
        for run in runs:
            characters[run+char] = [run] + rawCharacters[char]
    return characters
characters=expandCharacters()

# Given a filename, return a list of applications, each a dictionary
def parseCSV(filename):
    with open(filename, newline='') as f:
        r = csv.reader(f)
        apps = []
        for fields in r:
            if fields[0]=='Timestamp': #header line
                continue
            app = {}
            for col, field in zip(cols,fields): # zip_longest?
                if field=='Indifferent' or field=='': field=0
                if field=='Absolutely not': field=-1
                if field=='Yes Please': field=1
                if col=='days': field=parseDays(field)
                app[col]=field
            apps.append(app)
        return apps

# s will look like "Friday (22 Sept 2017) 7–11?, Saturday (23 Sept 2017) 1–5?, Saturday (23 Sept 2017) 7–11?, Sunday (24 Sept 2017) 1–5?, Sunday (24 Sept 2017) 7–11?"
def parseDays(s):
    r = []
    if "Friday (22 Sept 2017) 7–11?" in s: r.append("friEve")
    if "Saturday (23 Sept 2017) 1–5?" in s: r.append("satAft")
    if "Saturday (23 Sept 2017) 7–11?" in s: r.append("satEve")
    if "Sunday (24 Sept 2017) 1–5?" in s: r.append("sunAft")
    if "Sunday (24 Sept 2017) 7–11?" in s: r.append("sunEve")
    return r
    
# How good is it to cast this person in this role?
def score(app,char):
    s = bias
    for attr in characters[char]:
        if attr in app: s += app[attr]
    return s

# True iff this app can play as this character
# check run assignments & rejected roles
def permit(app,char):
    timing = False
    for day in app['days']:
        if day in characters[char]:
            for attr in characters[char]:
                if attr in app and app[attr]==-1:
                    return False
            return True
    return False
    

# produce a dicionary of roles; for each role, a list of
# apps that can fill it & their score.
def plausible(apps,characters=characters):
    out={}
    for char in characters.keys():
        ps=[]
        for app in apps:
            if permit(app,char):
                ps.append([app['email'], score(app,char)])
        out[char]=ps
    return out

# a dictionary mapping email addresses to the list of weighted roles they can fill.
def preferences(apps,characters=characters):
    out={}
    for app in apps:
        ps=[]
        for char in characters.keys():
            if permit(app,char):
                ps.append([char, score(app,char)])
        out[app['email']]=ps
    return out

# * The theory of casting
#
# Each role is a variable that can take on values from the range of
# what's "plausible" above---or to a special "not cast" standin (i.e.,
# Null.  Why multiple nulls?  because it's nicer if I can just say the
# roles have Distinct() values).
#
# Those restrictions + Distinct is enough to get *a* casting, but
# doesn't handle two important things:
#
# 1) Runs only count if they're full
# 2) Roles work better with some people than with others.
#
# We solve those together.  The score of a casting is the sum of
# scores of assignments in each *full* run.  Almost-full runs don't
# count for anything.  Then we ask Z3 to maximize that score.
#
# One more problem: some people haven't said they want anything, so
# casting them is neutral.  That's probably not right, and I don't
# love any current solution.  My current best answer is to add a
# "bias" number for casting *anybody*.  Scores all go up, and
# intuitively we prefer casting people who applied even if they said
# "indifferent" to everything.  After all, they applied!

def z3score(char, roles, apps, fullApps):
    return Sum([If(roles[char] == apps[app], score(fullApps[app],char), 0) for app in apps.keys() if "null" not in app])

def z3scores(apps, roles,fullApps):
    return Sum([z3score(role,roles,apps,fullApps) for role in roles.keys()])

def setup_z3(rawApps):
    p = plausible(rawApps)
    App, apps_ = EnumSort('App', [app['email'] for app in rawApps] + ['null' + role for role in characters.keys()])
    apps = dict(zip([r['email'] for r in rawApps] + ['null' + role for role in characters.keys()], apps_))
    fullApps = dict(zip([r['email'] for r in rawApps], rawApps))
    roles = {}
    for role in characters.keys():
        roles[role] = Const(role,App)
    s = Optimize()
    for (name,role) in roles.items():
        s.add(Or([role == apps[email] for (email,score) in p[name]] + [(role == apps['null' + name])]))
    # the Optimize() solver doesn't support Distinct natively, so we simplify it out
    s.add(simplify(Distinct(list(roles.values())),blast_distinct=True)) 
    total = Int('total')
    runHappening = {}
    for run in runs:
        runHappening[run] = Int(run)
    # FIXME, ignores whether run is happening
    # worse FIXME, doesn't yet exist!
    s.add(z3scores(apps,roles,fullApps) > target)
    print("Checking model.")
    if debug: print(s)
    print(s.check())
    try:
        m = s.model()
        if debug:
            print(m)
        if debug:
            print("Found model with score %r." % m.eval(z3scores(apps,roles,fullApps)))
        if debug:
            print(s.statistics())
        return (s,m)
    except:
        print("unsatisfiable constraints")
   
          

if __name__ == '__main__':
    try:
        apps = parseCSV(sys.argv[1])
    except:
        print("Usage: cast input.csv")
        exit(1)
    if debug: print(apps)
    casting = plausible(apps)
    prefs = preferences(apps)
    if debug: print(casting)
    print("Loaded Preferences:")
    for (pref,roles) in prefs.items():
        print(("%20s: %r" % (pref,sorted(roles,reverse=True,key=itemgetter(1)))))
    (_, m) = setup_z3(apps)
    print(m)
    # for debugging a very picky app
    # print([app for app in apps if app['email']=='brians@example.com'])

            
        
