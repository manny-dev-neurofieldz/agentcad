# plate_recovery (build123d, rebuilt from a STEP)

A plate with a row of through holes, written as a program from an original known only as a STEP file.
The holes' radius and pitch are the numbers the probes recovered (`probe inventory`, `probe section --arcs`),
kept as parameters. Its walkthrough, WALKTHROUGH.md, starts from numbers read off a picture and lets
`agentcad compare` say which are wrong.

What it exercises: recovering parameters from exact edges, the loop-count gate, a window per feature.
