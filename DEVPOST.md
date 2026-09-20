## Inspiration

We went to Federato's workshop at the start of the hackathon and their goal stuck with us. They build software that helps insurance carriers get to the right risks faster, so underwriters can spend their time on the submissions that actually matter instead of grinding through a queue one record at a time. That is a real problem for their clients, and it is the kind of problem an AI agent should be good at.

So we built one that does that specific job against their API.

## What it does

Federato Agentic reads a carrier's open submission queue, figures out what each account actually looks like, scores every submission against the carrier's appetite guidelines, and gives back a ranked list with a written reason for each position.

It runs on three agents with separate contexts:

- a planner that decides what to query and says up front what it expects to find
- an executor that runs the query and adapts when the API returns something unexpected
- a critic that only sees the question, the hypothesis, the query and the result, and rules on whether the data actually supported it

Because the critic never sees the planner's reasoning, it cannot just agree with it. That is what makes the read on an account's claim history and exposure worth trusting.

You can also click into any figure in a submission's report and the agent explains it: why a submission scored what it did, which queries produced the number, and which parts came from a fixed rule versus a model.

## How we built it

Python and FastAPI on the backend for the schema discovery, the scorer, the three agent loop and the reasoning trace. React and JavaScript for the dashboard, with CSS built on Federato's own design tokens. Anthropic's API powers the planner, the critic and the written explanations.

One rule shaped everything: the models decide what to ask, and a deterministic scorer decides what a submission is worth. The agents only get two tools, run a query or hand submissions to the scorer. So the same submission gets the same score on every run.

## What we learned

Our first version was a single agent that wrote a hypothesis and then read its own results. It agreed with itself almost every time. Splitting the critic into its own context with a narrow brief is what made the output actually reliable, and it ended up being the decision the whole project rests on.

The other lesson was that the hard part of building an agent is choosing what the model is allowed to decide. Letting it improvise appetite judgment would have made the scores unrepeatable, so we kept that part fixed and gave the models the query planning instead.
