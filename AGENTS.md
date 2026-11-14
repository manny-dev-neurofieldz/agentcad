# agentcad 0.1.0.dev0

Extensible agentic feedback loop for parametric 3D CAD design

This file was written by `agentcad plugin export --target agents-md`. It names what agentcad can do and where its know-how lives; the know-how itself stays in the installed command, so read it there and export again after upgrading.

## How to use it

- Every capability is a command: `agentcad --help`, then `agentcad <command> --help`.
- Every command has a policy that says what it means and how to use it. Before using a command, find its policy below, pick the question you have, and read that section: `agentcad policy read <name> --section <number>`. `agentcad policy navigate <name>` shows a guide again.
- The skills are workflows that read the policies in the right order; follow one when its moment comes.
- The policies are written in the policy format the [MacEff](https://github.com/cversek/MacEff) agent framework reads; `agentcad plugin export --target maceff` writes them as a policy root it can mount.

## Skills

- **design-session**: Use when designing, revising or replicating a part with agentcad, from before the first line of source to the finalize. Walks the session loop and reads the rules for each step from the installed agentcad policies.
- **fit-check**: Use before printing a mating pair, after any change to a mate's parameters, and whenever a slot, key, bore or seat is sized to another part. Declares the mate from both parts' sources and measures it with both bodies posed, instead of trusting either part alone.
- **print-prep**: Use when a finished part is headed for a printer: checking it against the printer's rules, stating how it should print, staging it for an output target, reading the sliced file before it prints, and fetching files or status from a printer host.
- **render-gate**: Use whenever agentcad has produced an image or a page (an iteration's renders, agentcad render, fit and compare views, a toolpath page, a viewer) and before acting on it or sending it to anyone. Looks first, then measures what looking cannot settle.
- **reverse-engineer**: Use when replicating an existing part from its STEP, mesh or design record, or revising a part whose source is lost. Recovers the part's intent with agentcad's probes, builds it forward in a session and judges it feature by feature against the original.
- **review**: Use before calling a design done, and whenever asked to review someone else's design. Prepares a frozen review packet as the author, or works through a review as the reviewer: build and probe first, the author's conclusions last, a rubric scored with evidence, one revision.
- **start**: Use when asked which agentcad skill, workflow or command fits a goal, when arriving at agentcad with a goal and no map of its commands, or when a task changes kind (from designing to fitting, from a finished part to a printer). Routes the goal to the skill and the policies that serve it.

## Commands

- `agentcad check`: Check HTML viewer for JS errors
- `agentcad compare`: COMPARE: loop counts per plane (a gate), sampled deviation, overlays
- `agentcad config-init`: Create agentcad.toml in current dir
- `agentcad config-show`: Show resolved project config
- `agentcad duties`: The work the records say is owed: verdicts to record, plans past their day, fits to re-run
- `agentcad export`: Export CAD source to STL or another format
- `agentcad fit`: Pose two parts and measure interference, clearance, mate windows, insertion
- `agentcad gallery build`: Build the gallery page and copy the viewers under it
- `agentcad gallery check`: Verify every link and thumbnail of a built gallery
- `agentcad gcode check`: Compare a sliced file's settings with the [slice] intent; exit 1 on an error
- `agentcad gcode compare`: Two sliced files side by side: time, filament, layers, supports, objects, settings that differ
- `agentcad gcode decode`: A .bgcode as plain G-code (plain files pass through)
- `agentcad gcode info`: Header, block table, printer and print metadata, thumbnails
- `agentcad gcode summary`: Layers, filament, extrusion by object and feature, where supports are
- `agentcad gcode supports`: Where supports touch each object: contact bands (bed frame)
- `agentcad gcode thumbnails`: Write the thumbnails a .bgcode carries
- `agentcad gcode view`: A standalone page of the toolpaths: feature colours, toggles, layer range
- `agentcad info`: Show engine and environment info
- `agentcad new-project`: Create a design project folder
- `agentcad open`: Print project path
- `agentcad plugin export`: Write agentcad's know-how for a harness into a folder (empty, new, or an earlier export for the same target)
- `agentcad plugin hook`: Run one of the plugin's hooks on the harness's JSON payload (stdin)
- `agentcad policy list`: Installed policies and the commands each governs
- `agentcad policy navigate`: A policy's navigation guide: its numbered topics and questions
- `agentcad policy read`: Read a policy, a section of it (with subsections), or a line range
- `agentcad printer files`: The files on the printer's storage, newest first, with both names
- `agentcad printer get`: Download one file from the printer, found by its short name or its display name
- `agentcad printer list`: The printers the host knows, with their state
- `agentcad printer status`: What the printer is doing: state, temperatures and the running job
- `agentcad printers`: The printers QC knows: process, build volume, nozzle, defaults
- `agentcad probe draft`: Draft per face against a pull direction: release, drag, undercut; faces along the pull reported, not judged
- `agentcad probe fillet`: Why a fillet fails: the selected chain on the LIVE part at the call, steps under 0.2 mm, sizes each edge takes
- `agentcad probe inventory`: bbox, volume, census, cylinder axes, loops on planes
- `agentcad probe knobs`: Which parameters of a program matter: base, plus and minus a delta per knob; flags saturated and dead knobs
- `agentcad probe rays`: Material and void intervals along lines and radial fans: wall thickness, bore depth, gaps
- `agentcad probe section`: Closed loops of exact edges on named planes (loops.json); an STL gives polylines with extents
- `agentcad probe sketches`: DRAWN vs APPLIED: a design dump's sketches in mm with construction flags, parameters, timeline
- `agentcad projects`: List all AgentCAD projects
- `agentcad qc`: Judge a project's latest iteration against its printer's design rules
- `agentcad records check`: Check every record under a library or project folder, or one record file
- `agentcad render`: Render CAD source to PNG images
- `agentcad session finalize`: Finalize session: STL exports + HTML viewer
- `agentcad session iterate`: Add iteration: render source file, record
- `agentcad session note`: Add analysis note to current iteration
- `agentcad session reopen`: Continue a finalized session (numbering carries on)
- `agentcad session start`: Start a new design session
- `agentcad session status`: Show session state
- `agentcad session tag`: Freeze the latest iteration under tags/<name>/ for a review
- `agentcad stage`: Write a finalized project's parts, posed and placed, for an output target
- `agentcad status`: Show project status
- `agentcad targets`: Registered output targets and the capabilities each declares
- `agentcad viewer`: Regenerate HTML viewer from project files

## Policies: what to ask of each

### agentcad-build123d: build123d Practice: Programs That Keep Their Promises

Commands: `none`

**1 The Program**
- Which values should be parameters, and which derived?
- How are dead knobs and silent couplings found?
- What should a program assert?

**2 Construction Practice**
- Which construction pitfalls have cost time, and how is each avoided?

**2.1 Fillets and Rounds**
- How are fillets and rounds made so they build and stay where they belong?

**2.2 Revolved and Axisymmetric Bodies**
- Where do the features of a revolved body go?

**2.3 Sketches, Lines and Chains**
- What goes wrong with sketches, lines and chains?

**2.4 Lofts**
- How are lofts made, thickened and checked?

**2.5 Bodies That Meet**
- How should bodies that meet be joined?

**3 After Every Feature**
- What is read after each feature, and why is a valid solid not enough?

**4 Reading Drawings**
- How is an unlabelled rounded section read?

**5 Recipes**
- How are a program's knobs checked for life, as commands?

**6 Constraints to Probe**
- Which command shows each pitfall, before it ships?

**7 Integration with Other Policies**
- Which policies hold the engine, the probes and the review this practice relies on?

**8 Anti-Patterns**
- Which habits make a program lie?

**9 Evolution and Feedback**
- How does this policy change?

### agentcad-compare: Compare: Does the Candidate Match the Original, and Where Not

Commands: `agentcad compare`

**1 What Compare Takes**
- Which sources can be compared, and with which instruments?
- How are a program's parameters overridden?

**2 The Loop-Count Gate**
- What does the gate compare, and when does it fail?
- What does a loop cap do to it?

**3 Windows and Overlays**
- How is a window named and placed on a section?
- What does a window report, and what images does compare write?

**4 Sampled Deviation**
- What does the deviation measure, in both directions?
- What sets its floor, and what does it not show?

**5 Reading a Comparison**
- In which order are the numbers read, and what does each prove?

**6 Recipes**
- What does a comparison that passes look like, and one whose gate fails?

**7 Constraints to Probe**
- Which limits of a comparison are found by a command before its numbers are trusted?

**8 Integration with Other Policies**
- Which policies feed and use a comparison?

**9 Anti-Patterns**
- Which readings of a comparison mislead?

**10 Evolution and Feedback**
- How does this policy change?

### agentcad-design-practice: Design Practice: Posture, Pins and Evidence

Commands: `none`

**1 Posture**
- When is a design estimated, and when is it engineered?
- What is a design faithful to?

**2 The Spec by Reconciliation**
- How is a spec written so its numbers agree with each other?
- What is decided before any dimension?

**3 Pins Before Contact**
- What is predicted before the first build, and why written down?
- Which pin catches what the aggregate pins miss?

**4 Every Iteration**
- What is read after every iteration, and which instruments count as evidence?

**5 Couplings, Faces and Deltas**
- How is a number kept from drifting between two features?
- What is checked before a feature is added to a face?
- How is a feature known to have done what was asked?

**6 Mates and Clearances**
- How is a mate stated and tested?
- How is a clearance chosen for a real material?

**7 Orientation and Process**
- How is a print orientation decided?

**8 Recipes**
- How is a feature's delta asserted, and a load-bearing dimension pinned, as commands?

**9 Constraints to Probe**
- Which command answers each practice, so that it is checked instead of trusted?

**10 Integration with Other Policies**
- Which policies carry out each step?

**11 Anti-Patterns**
- Which habits let a design pass while being wrong?

**12 Evolution and Feedback**
- How does this policy change?

### agentcad-design-review: Design Review: A Peer's Rubric

Commands: `none`

**1 The Packet**
- What does an author hand a reviewer?
- Why is the design frozen first?

**2 The Order of Work**
- What does a reviewer do before reading the author's conclusions?
- Which probes find what a render hides?

**3 The Rubric**
- On what is a design scored, and with what evidence?

**4 Findings and the One Revision**
- How are findings ranked and grouped?
- What is the one revision, and how is it chosen?

**5 What a Review Produces**
- What does the record of a review hold, and what does a reviewer not do?

**6 Recipes**
- How is a packet frozen, and how does a reviewer build and probe it before reading anything the author concluded?

**7 Constraints to Probe**
- Which of the reviewer's checks is answered by which command?

**8 Integration with Other Policies**
- Which policies give a reviewer its instruments?

**9 Anti-Patterns**
- Which reviews measure nothing?

**10 Evolution and Feedback**
- How does this policy change?

### agentcad-engines: Engines: The CAD Kernels Behind One Contract

Commands: `agentcad info`

**1 Engines and the Contract**
- What does every engine do, and what does it report?
- How is an engine chosen for a command?
- How are the installed engines and their versions listed?

**1.1 Settings**
- Where are an engine's settings written, and what happens to a key it does not know?
- Which settings does every engine accept?

**1.2 Measured Metadata**
- Which measurements can an engine report, and what does a missing one mean?
- How does an engine that measures nothing on render still feed the tray?
- Which keys give QC a program's declarations, and the resolution and frame of a mesh, and which engine supplies each?

**2 Python Sources: the Program Contract**
- What must a Python source define?
- How do `-D` overrides reach the program, and with which types?
- What happens when a source defines no build function?

**3 build123d**
- What is build123d for, and which settings tune it?
- What does it measure?

**4 OpenSCAD**
- Which OpenSCAD binary and libraries does the engine use?
- What does it measure, and from what?

**5 VoxelCAD**
- What is VoxelCAD for, and how is its grid sized?
- Which surface pipeline does it render and export with?
- What does it measure, and what can it not?

**6 Camera Presets**
- Which views can be rendered, and which are rendered by default?

**7 Adding an Engine**
- What must a new engine implement, and what checks it?

**8 Choosing an Engine**
- What does each engine do well, and what can it not do?

**8.1 Moving a Part Between Engines**
- How does a part built in one engine continue in another?

**9 Recipes**
- What does a first render and export look like in each engine?

**10 Constraints to Probe**
- Which limits of an engine are found by a command before they cost an iteration?

**11 Integration with Other Policies**
- Which policies use the engines?

**12 Anti-Patterns**
- Which uses of an engine mislead?

**13 Evolution and Feedback**
- How does this policy change?

### agentcad-fit: Fit and Mates: Testing a Mate with Both Bodies

Commands: `agentcad fit`

**1 Declaring Mates**
- Where is a mate declared, and what does each part state about its side?
- What do the datums fix, and what is left free when one is missing?

**1.1 The Assembly's Declaration**
- What does an assembly state about a mate that its parts do not?
- How does a mate name the two parts it joins?

**2 Posing the Pair**
- How is the second body placed when both parts declare datums?
- How is it placed when they do not?

**3 What Fit Measures**
- What do interference and clearance report, and what can neither show?
- What is a window, and how is it measured?
- What does the contacts report answer that a window does not?
- What do the sampling options change?

**3.1 The Insertion Sweep**
- How is a part that binds on the way in found?

**4 Verdicts**
- When does a window fail, and when is it unmeasured?
- What does the overall verdict say, and when does the command exit non-zero?

**5 The Views**
- Which images does fit write, and how is overlapping material marked?

**6 Records**
- What does a fit record carry, and where is it written?
- What does session finalize do with declared mates?

**7 Recipes**
- What does a declared mate look like when it passes, and when the parts overlap?

**8 Constraints to Probe**
- Which limits of a fit are found by a command before its verdict is trusted?

**9 Integration with Other Policies**
- Which policies govern the parts before and after a fit?

**10 Anti-Patterns**
- Which readings of a fit are wrong?

**11 Evolution and Feedback**
- How does this policy change?

### agentcad-gcode: Sliced Files: Reading What Will Actually Print

Commands: `agentcad gcode decode`, `agentcad gcode info`, `agentcad gcode summary`, `agentcad gcode check`, `agentcad gcode supports`, `agentcad gcode view`, `agentcad gcode thumbnails`, `agentcad gcode compare`

**1 What the Commands Read**
- Which files do the gcode commands accept?
- What does verification of a binary file check?
- Which command also accepts a project file, and what does it read from it?

**2 Decoding and Inspecting**
- How is a binary file turned into plain G-code?
- What does the block table and metadata show?

**3 The Summary**
- What does the summary report?
- How is a summary checked for being right?

**4 Settings Against Intent**
- How is a file's slicing checked against what the project intended?
- What happens when no intent is declared?

**5 Where Supports Touch**
- What is a contact band?
- In which frame are bands reported, and how are they placed on the part?

**5.1 Testing a Band Without Placement**
- How can a band be judged before the part's placement is known?

**6 The Toolpath Page**
- What does the toolpath page show, and how big may it get?

**7 Comparing Two Slices**
- What does the comparison report, and for which files?
- What does its exit status mean?

**7.1 What the Numbers Are**
- Where does the time come from, and when is it missing?
- How are objects matched, and what happens to one that is in only one file?
- Why can a band count change when the supports did not?

**7.2 Settings That Are Never Compared**
- Which settings does the comparison leave out, and why?

**8 Recipes**
- How is a sliced file read and checked against the intent it was meant to print with?
- How are two slices compared?

**9 Constraints to Probe**
- Which limits of reading a sliced file are found by a command first?

**10 Integration with Other Policies**
- Where do sliced files meet the session and the manifest?

**11 Anti-Patterns**
- Which readings of these reports are wrong?

**12 Evolution and Feedback**
- How does this policy change?

### agentcad-plugin: Plugin Export: agentcad's Know-How Written Out for an Agent Harness

Commands: `agentcad plugin export`, `agentcad plugin hook`

**1 What an Export Holds**
- Which files does an export write, and where do they come from?
- What does an export never hold?

**1.1 The Other Targets**
- What does the policy root for MacEff hold, and which folder is mounted?
- What does the AGENTS.md carry of a policy, and what does it leave in the command?
- How does a tool call become a command line?

**2 Exporting**
- Which targets are there, and what does each flag do?
- What happens to the folder written into?
- When is an export refused?

**3 Checking and Using It**
- How is an export checked before it is used?
- What must be true where the plugin is used?

**4 The Hooks**
- What does each hook tell a session, and when does it say nothing?
- Which edits does the library guard refuse, and how does a library declare them?
- What does the guard not see?
- What happens where the agentcad command is missing or at another version?

**5 Recipes**
- What does each export write, and how is it checked?

**6 Constraints to Probe**
- Which limits of an export are found by a command before a harness loads it?

**7 Integration with Other Policies**
- Which policies do the exported skills read?

**8 Anti-Patterns**
- Which uses of an export defeat it?

**9 Evolution and Feedback**
- How does this policy change?

### agentcad-policies: Policies: How agentcad Explains Itself

Commands: `agentcad policy list`, `agentcad policy navigate`, `agentcad policy read`

**1 Finding and Reading**
- How are the installed policies listed?
- How is a policy read without reading all of it?

**2 The Format**
- What does a policy file contain, and in what order?
- How are sections numbered?

**2.1 Parsing Rules**
- How is the navigation guide separated from the content?
- How is a section and its subsections found?

**2.2 The Enabling Pattern**
- What does every policy say beyond what its commands do?
- How is a recipe written so that it runs?
- How is a real constraint stated, so it can be checked instead of obeyed blind?
- How is a flow drawn?

**3 The Contract**
- Which commands must a policy cover, and which of their flags must it name?
- What checks hold every policy to the format and the pattern?

**4 Recipes**
- How is a policy found, navigated and read, as commands?

**5 Constraints to Probe**
- What should a policy author check before a change is done?

**6 Integration with Other Policies**
- Where else can these files be read?
- How should a skill or a document refer to a policy?

**7 Anti-Patterns**
- Which ways of writing or citing policies fail?

**8 Evolution and Feedback**
- How does this policy change?

### agentcad-print-intent: Print Intent: Stating a Print Once, Staging It Anywhere

Commands: `agentcad stage`

**1 Neutral Intent**
- Where is print intent written, and which keys does it hold?
- Where does it go when a session is finalized?

**2 Native Settings**
- Where are a target's own settings written?
- Which settings does a bare slice table belong to?
- What happens when a native setting disagrees with the intent?

**3 Staging**
- What does stage write, and from what?
- How is a part posed and placed on the bed?
- How does a target that starts from the user's own configuration get it?
- What does stage print besides the files, and how does a refusal look?

**4 Recipes**
- How is a finished part staged for a target, and what is refused before anything is written?

**5 Constraints to Probe**
- Which limits of staging are found by a command before a job is written?

**6 Integration with Other Policies**
- Which policies govern the targets and the checks around staging?

**7 Anti-Patterns**
- Which ways of stating intent defeat it?

**8 Evolution and Feedback**
- How does this policy change?

### agentcad-printer-hosts: Printer Hosts: Reading What a Printer Holds, Read-Only

Commands: `agentcad printer list`, `agentcad printer files`, `agentcad printer get`, `agentcad printer status`

**1 Hosts and Capabilities**
- What is a printer host, and what can one declare?
- What happens when a host is asked for something it does not declare?

**2 Read-Only by Contract**
- What makes a host read-only, and who checks it?

**2.1 The One Network Function**
- Which part of a host may touch the network, and what must it do first?

**2.2 What the Contract Test Checks**
- How does the test prove that no other path to the network exists?

**3 Credentials**
- Where do a host's address and credentials live, and how are they protected?

**3.1 Where They Come From**
- Which environment variables and which file give the settings, and which wins?

**3.2 The Credentials File**
- Which file modes are refused, and what does the refusal say?

**3.3 What Is Never Shown**
- Where must a credential never appear?

**4 The Commands**
- What do the four commands do, and what do they have in common?

**4.1 Choosing a Host**
- How is a host chosen, and where may the option go?

**4.2 Listing Printers, Files and Status**
- What do list, files and status report, and in what order?

**4.3 Downloading a File**
- How is a file named, where does it go, and what happens on a failed download?

**4.4 Exit Status**
- What do the exit codes mean?

**5 The PrusaLink Host**
- Which routes does the PrusaLink host read, and how does it authenticate?

**5.1 Names: Short and Display**
- How are a file's two names handled?

**5.2 Authentication**
- How does the host answer the printer's Digest challenge, and what does it refuse to do?

**6 Adding a Host**
- What does a new host implement, and what checks it?

**7 Recipes**
- What does a host command say when no host is configured?

**8 Constraints to Probe**
- Which limits of a printer host are found by a command first?

**9 Integration with Other Policies**
- Which policies use what a host fetches?

**10 Anti-Patterns**
- Which uses of a host mislead or put a printer at risk?

**11 Evolution and Feedback**
- How does this policy change?

### agentcad-printers: Printers: What Each Machine Can Make

Commands: `agentcad printers`

**1 The Registry**
- Which printers are known without any configuration?
- Where else do printers come from, and which source wins?
- How is the registry listed?

**2 Process Defaults**
- Which limits does each process set by default?
- How are the defaults named in a finding?

**3 Adding a Printer**
- What does a printer table hold?
- What happens to a table that cannot be read?

**4 Printers from a Sliced File**
- Which settings of a sliced file describe its printer?

**5 Recipes**
- How are the known printers listed?

**6 Constraints to Probe**
- Which limits of the printer registry are found by a command first?

**7 Integration with Other Policies**
- Which policy uses the registry?

**8 Anti-Patterns**
- Which uses of the registry mislead?

**9 Evolution and Feedback**
- How does this policy change?

### agentcad-probe-construction: Construction Probes: Why a Fillet Fails, and Whether a Part Releases

Commands: `agentcad probe fillet`, `agentcad probe draft`

**1 Why a Fillet Fails**
- How is a program stopped at one fillet or chamfer call?
- What does the probe report about the selected edges and the part they belong to?

**1.1 Acting on the Result**
- What does a short step beside the chain mean, and what is the fix?
- Why is shrinking the radius until it builds the wrong fix?

**2 Draft Against a Pull Direction**
- How is draft measured on each face, and with what sign?
- Which faces are not judged, and why?
- How is a minimum draft enforced?

**3 Recipes**
- What does a fillet probe and a draft check look like, as commands?

**4 Constraints to Probe**
- Which limits of the construction probes are found by a command first?

**5 Integration with Other Policies**
- Which policies cover the construction these probes diagnose?

**6 Anti-Patterns**
- Which ways of handling a failing fillet or a draft check mislead?

**7 Evolution and Feedback**
- How does this policy change?

### agentcad-probe-inspect: Inspection Probes: Rays, Knobs and the Census

Commands: `agentcad probe rays`, `agentcad probe knobs`, `agentcad probe inventory`

**1 Choosing the Probe**
- Which question does each inspection probe answer?
- When is a render, a count or a section the wrong tool?

**1.1 Exact and Sampled Sources**
- What does a program or STEP source give that a mesh does not?
- How does an output say which one it read?

**2 Rays: Material and Void Along Lines**
- What does a ray report, and for which sources?

**2.1 Lines and Fans**
- How is a line given, and how is a fan?
- How are fan angles counted?
- How far is a line followed, and where is that recorded?

**2.2 Reading the Intervals**
- What do entry, exit and length mean?
- What do clipped and enclosed say?
- How is a wall thickness read from a ray?

**2.3 What a Ray Cannot Tell**
- How far may a mesh and an exact source differ?
- What does a line that touches a surface, or lies in one, report?
- What does a warning about a mesh that is not closed mean?

**3 Inventory and the Census**
- What does inventory report, and for which sources?

**3.1 When the Census Cannot See Analytic Types**
- When do inventory and the iteration tray say the representation hides analytic types?
- What follows from that warning?

**4 Meshes in probe section**
- What changes when probe section is given an STL?
- Where are the flags that apply to every source documented?

**4.1 Loops from Triangles**
- How does a mesh loop differ from an exact one?
- How is a plane that passes through vertices, or lies in a face, read?

**4.2 Radial and Axial Extents**
- What are the radial and axial extents of a loop?
- How are the axis and its centre chosen, and when must they be named?

**5 Knobs: Which Parameters Matter**
- What does a knob sweep run, and how many builds does it cost?
- How is the base moved, and how is a delta given?

**5.1 Reading the Verdicts**
- What do live, saturated, dead, partial and refused mean?
- What does a dead verdict not prove?

**6 Recipes**
- What do a width, an axis and a knob look like when measured, as commands?

**7 Constraints to Probe**
- Which limits of a probe are found by a command before its number is trusted?

**8 Integration with Other Policies**
- Which policies govern what surrounds these probes?

**9 Anti-Patterns**
- Which readings of these probes mislead?

**10 Evolution and Feedback**
- How does this policy change?

### agentcad-probe-recover: Recovering Curves: Arcs, Chains and Drawn Intent

Commands: `agentcad probe section`, `agentcad probe sketches`

**1 What Recovery Is For**
- When is recovering curves the right step, and when is a comparison enough?
- What does a recovered number carry with it?

**2 Reading Section Loops**
- What does `probe section` list, and for which planes?
- What limits does it apply, and how are they reported?

**2.1 The Frame**
- Which two coordinates are kept for each section plane?
- What do cw and ccw mean?

**2.2 Exact and Polylined Loops**
- How does a loop of exact edges differ from a polylined one?
- What does the record of a circular edge carry?

**3 Lines and Arcs from a Loop**
- How is a run of short edges turned into an arc?
- Which tolerances apply, and what does each one bound?
- What does each field of an arc mean?
- What happens to an edge that is neither a line nor an arc?

**3.1 Judging a Joint**
- What do tangent, kinked, not tangent, corner and skipped mean?
- Why is the centre distance alone not enough to call a joint tangent?
- What does scatter in the vertices do to the verdicts?

**3.2 Where the Reading Goes Wrong**
- Which inputs are read wrongly, and how can that be seen?

**4 A Loop as a Chain**
- What does the chain literal contain, and in which frame?
- Where do the literal and the listing go?

**4.1 Slivers**
- How are segments shorter than a stated length handled?

**4.2 Edges that Are Neither**
- What is done with an edge that is neither a line nor an arc?

**4.3 From the Literal to a Face**
- How is a literal turned into a face?

**5 Design Dumps**
- What is a design dump, and what does `probe sketches` print from it?
- Which part of the output needs no CAD backend?

**5.1 The Dump Format**
- Which fields does the reader use, and in which units?
- What happens to a field or a curve type it does not know?

**5.2 DRAWN and APPLIED**
- What does each label claim?
- How is a dimension matched against a part, and with what tolerance?
- Which sketches cannot be matched, and what does the output say then?

**6 Recipes**
- How is a part's outline recovered as a chain a program can build from?

**7 Constraints to Probe**
- Which limits of a recovered curve are found by a command before it is built from?

**8 Integration with Other Policies**
- Which policies govern what follows a recovery?

**9 Anti-Patterns**
- Which readings of these reports are wrong?

**10 Evolution and Feedback**
- How does this policy change?

### agentcad-projects: Projects: Where a Design Lives and How It Is Configured

Commands: `agentcad new-project`, `agentcad projects`, `agentcad status`, `agentcad open`, `agentcad config-init`, `agentcad config-show`

**1 What a Project Is**
- What makes a folder a project, and what does it hold?
- How does a command find the project it is given?

**1.1 Where Outputs Go**
- Where does a session write its renders, exports and record?
- What must a project kept outside the designs directory state?

**1.2 Part Subprojects**
- How does an assembly declare its parts, and how many of each it uses?

**2 Creating a Project**
- How is a new project created, and what does it start with?
- How is an existing folder made a project?

**3 Inspecting Projects**
- How are the projects listed?
- How is one project's state read, or its path printed?
- How is the configuration a command will use shown?

**4 The agentcad.toml Tables**
- Which tables does the file hold, and which policy governs each?
- Which values does the template state that the designer has not chosen?

**5 Recipes**
- How is a project made where you want it, and its settings read back?

**6 Constraints to Probe**
- Which of a project's settings are checked by a command before a session relies on them?

**7 Integration with Other Policies**
- Which policies govern the work done inside a project?

**8 Anti-Patterns**
- Which ways of placing or configuring a project mislead?

**9 Evolution and Feedback**
- How does this policy change?

### agentcad-prusaslicer: PrusaSlicer Target: A Project File from a Complete Configuration

Commands: `none`

**1 The Base Configuration**
- What is the base configuration, and why does agentcad not ship one?
- Which files can supply it, and how is it passed to the target?
- What makes the target refuse a configuration?

**1.1 The Default**
- How is a default base configuration set, and where must it not be kept?

**2 The Settings a Project Carries**
- In what order are the settings layered?

**2.1 The Mapping**
- Which neutral intent keys have a PrusaSlicer setting, and in what form is each written?
- Which keys are reported as not mapped, and why?

**2.2 Overrides and Refusals**
- What happens when a native setting disagrees with the intent?
- When is a key refused by name?
- What does a range in a native table do?

**2.3 What Is Never Written**
- Which settings never reach a project?

**3 The Project File**
- What does the 3MF hold, and in what order?
- How is a part's place stored?
- What is written for an object, and what is not built?

**4 The Bed**
- What is checked before a file is written, and against which bed?

**5 Reading**
- What does the target read, and which command checks a project?
- How does the target slice a project, and how is the output named?

**6 Recipes**
- How is a part staged from a configuration PrusaSlicer wrote, and its project read back?

**7 Constraints to Probe**
- Which of PrusaSlicer's limits are found by a command first?

**8 Integration with Other Policies**
- Which policies govern the pieces around this target?

**9 Anti-Patterns**
- Which uses of this target mislead?

**10 Evolution and Feedback**
- How does this policy change?

### agentcad-qc: QC: Design Rules Judged Before a Print

Commands: `agentcad qc`

**1 What QC Judges**
- Which rules does QC measure, and how is each measured?
- Against which printer is a part judged?

**1.1 Bridges and Floors**
- When is a ceiling a bridge, and how is its span measured?
- How is a floor too thin across the layers found?

**2 Limits and Their Layers**
- Where does each limit come from, and in what order do the sources apply?
- How is a rule's severity changed or a rule turned off?

**2.1 Feature Annotations**
- How does a program declare its features, and what does a feature change about a finding?
- How does a program accept a finding, or loosen a limit, and where is that shown?
- How does a program stay runnable without agentcad?
- Which engines read a Python program's annotations, and what is different about a voxel part?

**2.2 Annotations from OpenSCAD**
- How does an OpenSCAD file declare a feature, a suppression or a pose?
- What must an annotation string avoid, and how exact are the numbers in it?
- Why does a finding from an OpenSCAD declaration name the file and no line?
- What happens when a declaration is printed again, or cannot be read?

**3 The Print Pose**
- How is the pose a part prints in declared, by the project or by the program?
- How does the build-volume rule use the pose and the bed?

**4 Reading a Report**
- What does a finding carry?
- What does a rule that is not measured mean?
- When is a wall read off a voxel mesh, and when is it left unmeasured?
- When does the command exit non-zero?

**4.1 Fixes by Sensitivity**
- Which knob moves a failing finding, in which direction and by how much?
- What does a knob that moves nothing, or only one way, look like?
- How many rebuilds does it cost, and how is that bounded?
- For which engines does it work?

**5 The Gate at Finalize**
- When does QC run at finalize, and when does it hold a part back?
- What does a held part look like, and how does it continue?

**6 Recipes**
- What does a QC pass over a finished part say, and how is it read?

**7 Constraints to Probe**
- Which limits of QC are found by a command before its verdict is trusted?

**8 Integration with Other Policies**
- Which policies govern the printers, the session and the engines around QC?

**9 Anti-Patterns**
- Which readings of a QC report are wrong?

**10 Evolution and Feedback**
- How does this policy change?

### agentcad-records: Records: Part, Job and Fit Records Others Can Rely On

Commands: `agentcad records check`, `agentcad duties`

**1 Record Files and Libraries**
- Which files are records, and what does a library hold?
- Which folders are not read, and what does a catalog add?

**2 Part Records**
- Which fields of a part record are structured, and what must each hold?

**2.1 Fit Records**
- What does a fit record state, and where can it live?
- What is a snapshot, and why record one?
- Why should a fit be recorded on both parts?

**3 Job Records**
- Which fields of a job record are structured, and what must each hold?

**3.1 Verdicts**
- Which verdicts can a print have, and what does each require?
- Where does a sentence about the print go?

**4 The Check**
- What does the check read, and what does it report?
- Which problems are errors and which are warnings, and what do the exit codes mean?

**5 Owed Work**
- Which work do the records say is owed, and from which fields?
- What makes two runs agree on the same duty?

**5.1 Declaring Owed Work on a Role**
- What does a dry run show, and what does applying change?
- How is a duty that was declared before recognised?
- What does the command never do to a role?
- What is reported when a closed duty's work is owed again?
- Why are the duties declared without dates?

**6 Writing Structured Fields from Prose**
- How is a structured field filled in from an older record without inventing anything?

**7 Recipes**
- How is a records library checked, and what does it say is owed?

**8 Constraints to Probe**
- Which limits of the records check are found by a command first?

**9 Integration with Other Policies**
- Which policies write or read these records?

**10 Anti-Patterns**
- Which ways of writing records defeat the tools that read them?

**11 Evolution and Feedback**
- How does this policy change?

### agentcad-render-export: Render and Export: A Single Look and a Single File

Commands: `agentcad render`, `agentcad export`

**1 Rendering a Source**
- What does a render produce, and where?
- Which views and size does it use, and which engine?
- What does the report show?

**1.1 When a Session Is the Better Tool**
- What does a lone render not give that an iteration does?

**2 Exporting a Source**
- Which formats can be written, and where does the file go?

**2.1 Variant Plates**
- How is one file written per value of a parameter?
- What is a variant plate for?

**3 Recipes**
- What does a quick look, with its report, look like as commands?
- How is a clearance plate written?

**4 Constraints to Probe**
- Which limits of a render or an export are found by a command first?

**5 Integration with Other Policies**
- Which policies govern what a render shows and what an export becomes?

**6 Anti-Patterns**
- Which uses of a lone render or export mislead?

**7 Evolution and Feedback**
- How does this policy change?

### agentcad-reverse-engineering: Reverse Engineering: Recovering a Part's Intent

Commands: `none`

**1 Before Starting**
- What must be decided before an original is read?

**2 Archaeology**
- Where does a design's own record survive, and what does each kind keep?
- How is a hypothesis labelled by where it came from?

**3 Inventory and Sections**
- What does a face census say about how a part was made?
- How are section loops read for parameters?

**4 Polylined Loops Are Arcs**
- How is a loop of many short lines read back into arcs?
- Which fits lie?

**5 Building Forward**
- How do the hypotheses and the recovered curves become a program?
- What is done with a body that was converted from a mesh?

**6 Verifying per Feature**
- How is a replication judged, and against which numbers?

**7 Editing a Solid Without Its Source**
- How is a feature removed from a solid that has no parametric source?
- How is such an edit verified and recorded?

**8 Recipes**
- What does recovering a part from its STEP and judging the rebuild look like, as commands?
- How are a mesh's polylines read back as arcs?

**9 Constraints to Probe**
- Which step of the method is checked by which command?

**10 Integration with Other Policies**
- Which commands carry out each step?

**11 Anti-Patterns**
- Which shortcuts recover the wrong intent?

**12 Evolution and Feedback**
- How does this policy change?

### agentcad-session: Design Sessions: the Iterate, Look, Record Loop

Commands: `agentcad session start`, `agentcad session iterate`, `agentcad session reopen`, `agentcad session tag`, `agentcad session note`, `agentcad session finalize`, `agentcad session status`

**1 The Session Loop**
- What is a session, and when is one better than a plain render?
- What is the order of work inside a session?

**1.1 Starting a Session**
- What does start create, and what do its defines do?
- What happens to an earlier session when one is started again?

**1.2 Iterating**
- What does one iteration produce?
- How do per-iteration defines differ from session defines?
- What does iterating a project with part subprojects do?

**2 Reading Each Iteration**
- What must be read after every iterate, before the next one?

**2.1 The Tray**
- What does the measured report contain?
- Which warnings does it raise, and what does each mean?

**2.2 The Render Gate**
- What must happen to a render before anyone acts on it or sends it?
- What can a render not show?

**3 Recording and Freezing**
- How are findings recorded against an iteration?
- When is a tag the right tool, and what does it freeze?
- How is a finished session continued?

**4 Finalizing**
- What does finalize write, and what does it reuse?
- What is the print manifest?

**5 Session Status**
- How is a session's state inspected?

**6 Recipes**
- What does a session look like from start to finalize, as commands?
- How is a revision frozen for a reviewer while work continues?

**7 Constraints to Probe**
- Which of a session's limits are found by a command before they cost an iteration?

**8 Integration with Other Policies**
- Which policies govern what happens after a session?

**9 Anti-Patterns**
- What mistakes does the loop exist to prevent?

**10 Evolution and Feedback**
- How does this policy change?

### agentcad-start: Start: agentcad by Goal

Commands: `none`

**1 Goals**
- Which goals does agentcad serve, and where does each one start?

**1.1 Design a New Part**
- Which skill, policies and first command design a part from nothing?

**1.2 Change a Part That Exists Only as a STEP or a Mesh**
- How is a part with no source recovered, rebuilt and judged against the original?

**1.3 Check a Fit**
- How are two mating parts measured together?

**1.4 Review a Design**
- How is a design reviewed, by its author or by someone else?

**1.5 Get a Part Printed**
- What lies between a finished part and a print?

**1.6 Make agentcad's Know-How Available in a Harness**
- How does another agent harness get the skills, the policies and the tool definitions?

**2 Choosing an Engine**
- Which engine does a new part start in?

**3 Recipes**
- What does the first quarter hour with agentcad look like, as commands?

**4 Constraints to Probe**
- What should be checked before trusting the map?

**5 Integration with Other Policies**
- Which policies does each goal lean on?

**6 Anti-Patterns**
- Which ways of starting cost the most later?

**7 Evolution and Feedback**
- When does this map change?

### agentcad-targets: Output Targets: What a Part Becomes on Its Way to a Machine

Commands: `agentcad targets`

**1 Targets and Capabilities**
- What is an output target, and what can one declare?
- What happens when a target is asked for something it does not declare?

**2 The Registry**
- How are the registered targets and their capabilities listed?
- Which targets are registered today?

**3 The Generic Target**
- What does the generic target write and read?

**3.1 Placement**
- How is a part's place on the plate stated, and in which convention?
- How does a plate file store the same placement?

**4 Adding a Target**
- What does a new target implement, and what checks it?

**5 Recipes**
- How are the registered targets and their capabilities listed?

**6 Constraints to Probe**
- Which limits of a target are found by a command first?

**7 Integration with Other Policies**
- Which policies use the targets?

**8 Anti-Patterns**
- Which uses of targets and placements mislead?

**9 Evolution and Feedback**
- How does this policy change?

### agentcad-viewer: Viewer and Gallery: Where a Design Is Seen

Commands: `agentcad viewer`, `agentcad check`, `agentcad gallery build`, `agentcad gallery check`

**1 The Project Viewer**
- What does a project's viewer show?
- How is the viewer rebuilt from the files on disk?

**1.1 Tags and Artifact Hosts**
- How is the viewer of a frozen tag rebuilt?
- How is a page written for a host that supplies its own document shell?

**2 Checking a Page**
- What does the page check catch, and what can it not see?
- What does the check need installed?

**3 The Gallery**
- What does a gallery card show, and which projects get one?
- When are viewers copied under the gallery, and when only linked?

**3.1 Checking a Gallery**
- What makes a built gallery broken?

**4 Recipes**
- How is a viewer rebuilt and a gallery built and checked, as commands?

**5 Constraints to Probe**
- What does a page or a gallery need before it is shown to anyone?

**6 Integration with Other Policies**
- Which policies produce what the viewer shows?

**7 Anti-Patterns**
- Which ways of presenting a design mislead?

**8 Evolution and Feedback**
- How does this policy change?
