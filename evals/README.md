# Live evaluation battery

`battery.py` runs ~134 scripted customer scenarios against the **real agent and real model** and checks each one automatically:

* the expected tool was (or was not) called;
* required / forbidden phrases in the reply (accent-insensitive regexes);
* global checks on every reply: no `**markdown bold**`, no invented website, no leaked internal text,
  and **every `R$` amount must come from a tool result** (or from the customer's own message).

```bash
python evals/battery.py                 # everything (4 parallel workers; ~20 min on the free tier)
python evals/battery.py c13 p0 r1       # only scenarios whose id starts with these prefixes
```

Results go to `evals/out/` (git-ignored). Each scenario sets its own simulated date, so results do not depend on today's date.

**Cost warning:** a full run makes ~400 model calls. The Gemini free tier allows a limited number of requests per day per model, so
two full runs in a day can exhaust it (the agent then reports an error until the quota resets).

Status of the last runs and what they led to is described in the main README ("Known limitations").
