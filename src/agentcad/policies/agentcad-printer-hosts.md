# Printer Hosts: Reading What a Printer Holds, Read-Only

**Type**: Capability Policy (print readiness)
**Scope**: Any agent or person fetching sliced files from a printer or checking what it is doing, or adding a printer host
**Status**: ACTIVE
**Commands**: agentcad printer list, agentcad printer files, agentcad printer get, agentcad printer status

## Purpose

A sliced file is only useful once it is out of the printer, and a print is only understood once its state is known. Until now both were done by hand: a file copied from the printer's web page, a status read off its screen. agentcad keeps a registry of printer hosts, each declaring what it can do, so that every host is used the same way and the next one needs no new command. The registry is read-only by contract: nothing in it can start, stop, upload, change or delete anything on a printer. This policy says what a host is, how the read-only rule is built and checked, where credentials live and what is never shown, how the commands behave, and what the PrusaLink host does.

## CEP Navigation Guide

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

**7 Integration with Other Policies**
- Which policies use what a host fetches?

**8 Anti-Patterns**
- Which uses of a host mislead or put a printer at risk?

**9 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 Hosts and Capabilities

A printer host is a service in front of one or more printers: a printer's own web interface, a farm server, a cloud queue. A host declares some of these capabilities, and each is a method of the same name:

- `list_printers`: the printers the host knows;
- `list_files`: the files a printer keeps;
- `download_file`: fetch one file by name;
- `job_status`: what the printer is doing now.

A capability a host does not declare raises an error that names the host and the capabilities it has; it is never a silent no-op, so a command can ask the registry what a host can do instead of trying and guessing. A host that cannot do anything yet still registers and says so.

## 2 Read-Only by Contract

No host can start a print, pause one, upload, rename or delete. That is not a habit of the commands; it is a property every host must have and the tests hold every registered host to. A host that needs a write is a different contract, with its own policy and its own review.

### 2.1 The One Network Function

In every host exactly one method performs network I/O. The class names it in `network_function`. Its first statement is a call to `require_read_only`, which refuses every HTTP method except GET and HEAD before a connection is opened. Network libraries are imported inside that method and nowhere else in the host's module, and nothing else in the module starts a process or opens a socket. Everything a host does goes through that method, including reading the body of a download, so a reader checks one function to know what a host can send.

### 2.2 What the Contract Test Checks

The contract test runs over every registered host and checks four things:

- the one network function refuses POST, PUT, PATCH, DELETE, OPTIONS, TRACE, CONNECT, a lower-case get and a method with a second request line smuggled in, and it refuses them before any connection is attempted;
- in the host's source, no network or process library is referenced outside that function, the function opens with `require_read_only`, and no write method is spelled out in it;
- every declared capability, run against a fake server on the loopback address, connects only from inside that function;
- the fake server saw nothing but GET and HEAD.

The test also keeps three hosts written to break the contract, and each must fail the check meant to catch it: one with no guard that posts, one with the guard whose method on the wire is built at run time (only the wire check can see it), and one that opens its own socket in another method. Every registered host must come with a fake server for the tests, or the suite fails; a guard in the tests fails any test that tries an address other than the loopback.

## 3 Credentials

A host needs an address and, for most, a user and a password. They are read from the environment or from a file in the user's own agentcad configuration folder. They are never read from a project, never written to one, and never printed.

### 3.1 Where They Come From

Settings are the host's `url`, `user`, `password`, and optionally `timeout` in seconds and `storage`. Each comes from the environment variable `AGENTCAD_<HOST>_<SETTING>` when that is set (for PrusaLink: `AGENTCAD_PRUSALINK_URL`, `AGENTCAD_PRUSALINK_USER`, `AGENTCAD_PRUSALINK_PASSWORD`, `AGENTCAD_PRUSALINK_TIMEOUT`, `AGENTCAD_PRUSALINK_STORAGE`), else from the table named after the host in `hosts.toml`, else from the host's default (PrusaLink's user is `maker`). The file lives in the agentcad user config folder, `$XDG_CONFIG_HOME/agentcad` or `~/.config/agentcad`, beside `printers.toml`:

```
[prusalink]
url = "http://192.0.2.10"
password = "the printer's PrusaLink password"
```

A URL may carry a scheme and a port but not a user name or a password; one that does is refused without being repeated.

### 3.2 The Credentials File

`hosts.toml` holds a password, so it must be private. A file that group or others can read, write or run is refused outright, with a message that names the file, shows its mode and gives the command that fixes it: `chmod 600` and the path. The check reads the mode of the file actually opened. The file is looked at whenever it exists, even if the environment supplies every value, so a forgotten world-readable copy is found rather than ignored. An unknown key in the table is refused by name, so a misspelled `password` is not mistaken for a missing one.

### 3.3 What Is Never Shown

A credential is not in an error message, a log line, the text a command prints, a JSON record, a repr, or a file written into a project. Errors say where to put a value, never the value; the settings object prints its user and password as asterisks; the Authorization header is not logged; the address is shown, the user and password are not. The tests run every command, on success and on failure, with distinctive credentials and look for them, and for the hashes derived from them, in everything printed, logged and written.

## 4 The Commands

All four are `agentcad printer`, ask the registry whether the chosen host declares the capability, make only the reads the host contract allows, and take `--json` for a record that carries a `schema` and the `host`.

### 4.1 Choosing a Host

`--host NAME` names a registered host; the default is `prusalink`. The option is accepted before the subcommand (`agentcad printer --host prusalink files`) and after it. An unknown name is an error that lists the registered ones.

### 4.2 Listing Printers, Files and Status

`agentcad printer list` prints the printers the host knows with their state. `agentcad printer files [PATH]` lists a folder of the printer's storage, newest first, each entry with its display name, its short name, its size when the printer states one, and its modification time as the printer reports it; `--storage` picks the storage (PrusaLink's default is `usb`) and `--limit N` shows only the newest N. `agentcad printer status` prints the printer's state, its temperatures and the running job, or says there is none.

### 4.3 Downloading a File

`agentcad printer get NAME -o PATH` downloads a file named by either of its names, with folders written as `folder/file`. `-o` (`--output`) is a file path, or a folder (an existing one, or a path ending in a slash) to keep the display name; without it the file goes to the current folder under its display name. A name the printer chose is reduced to its last path component before it is used as a file name, so a hostile name cannot write outside the folder. An existing file is not replaced without `--force`. The bytes are written to a `.part` file next to the target and renamed only when the whole reply has arrived and its length matches what the printer declared; a failed or truncated download leaves nothing behind. The record carries the byte count and the SHA-256 of what was written.

### 4.4 Exit Status

0 on success. 1 when the host could not be reached, refused the credentials, has no such file or answered with an error. 2 when the request or the configuration cannot be acted on: no address or credentials, an unsafe credentials file, an unknown host, a capability the host lacks, a file that would be overwritten.

## 5 The PrusaLink Host

`prusalink` speaks the v1 HTTP API of a printer's own PrusaLink service, over HTTP or HTTPS, with Digest authentication. It reads, always with GET: `/api/v1/info` and `/api/v1/status` for the printer, `/api/v1/files/<storage>/<folder>/` for a folder, `/api/v1/job` for the running job (no content means no job), and the path a listing entry names in `refs.download` for the file itself. It does not follow redirects, so a credential only goes to the address that was configured.

### 5.1 Names: Short and Display

A printer stores a file under a short (8.3) name and shows the name the slicer gave it. A listing carries both. `get` and `files` accept either: an exact match on either name first, then a match ignoring case. Two files that match the same name are an error that lists their short names; no match is an error that suggests close names. The download is fetched from the path the printer names for that entry, built from the short name only when the printer names none, and a path that is not a plain server-relative path is never fetched.

### 5.2 Authentication

The host sends the request, takes the printer's Digest challenge from the 401 reply, and sends the same request again with the answer. It supports MD5, SHA-256 and SHA-512-256 with `qop=auth` (and the older form without a qop), picks the strongest challenge on offer, and retries once when the printer says the nonce went stale. A second refusal is reported as rejected credentials and stops; the host does not loop. A printer that offers only another scheme (Basic, say) is refused with the schemes it offered, since the host speaks Digest only.

## 6 Adding a Host

A host subclasses the host base class, sets its name, the capabilities it declares and the name of its one network function, implements exactly those capabilities, and registers under a short lower-case name. It reads its settings through the shared credentials module, so the environment, the file mode check and the masking come with it. Its tests add a fake server for the contract test to run against; a registered host without one fails the suite. The contract test then holds the new host to everything in section 2 without being edited.

## 7 Integration with Other Policies

- `agentcad-gcode`: reading, checking and comparing the sliced files a host downloads.
- `agentcad-targets`: the output side, where a staged job is written for a slicer; hosts are the read side of the printer.
- `agentcad-printers`: the printer specifications QC judges against, which are not the same thing as a host.
- `agentcad-policies`: how this policy is found and read.

## 8 Anti-Patterns

- **A second network path**: a helper that opens a socket "just to check" breaks the one-function rule the contract test relies on.
- **A credential in a project**: an address and password in `agentcad.toml` or a script travel with the project; they belong in the environment or the private file.
- **Loosening the file mode to make the check pass**: the refusal names the command that fixes the mode; run it.
- **Following a redirect with the Authorization header**: the answer goes to the address that was configured, never to one a reply names.
- **Trusting a name from the printer**: a display name is data; it is cut to its last component before it names a local file.
- **Testing against the real printer**: the suite uses a fake server on the loopback address, and a guard fails any test that tries another address.

## 9 Evolution and Feedback

This policy ships with agentcad and changes with the hosts; a new host, capability or setting updates this policy in the same pull request.
