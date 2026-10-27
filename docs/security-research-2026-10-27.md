# Recent cyberattacks: causes, attack paths, recovery, and lessons for Avenra

**Research cutoff:** 27 October 2026  
**Avenra baseline:** `e4cbc83`, branch `tazio`  
**Coverage:** 18 incident, campaign, and vulnerability case studies, emphasizing recent October disclosures and technically informative 2026 investigations.

## Executive findings

The most important recurring failure is **trusted access becoming more powerful than intended**. Stolen application credentials, session tokens, publishing identities, CI runners, and administrative tools let attackers bypass protections aimed only at passwords or public login pages.

The strongest lessons for Avenra are:

1. **Revocation is the fix for an exposed credential.** Removing it from a file, chat, or Git history does not invalidate it. LiteLLM's October compromise began with a master key exposed in May and never revoked.
2. **Authorize the exact object and action.** Checking a parent case, collection, or account is insufficient when the request also identifies a child object belonging to someone else. Outline provides a particularly clear example.
3. **A trusted release can contain attacker code.** Signatures, official registries, passing dependency scans, and short-lived publishing credentials each cover only part of the problem.
4. **MFA is valuable, but session theft and malicious authorization remain possible.** Enrollment, recovery, session invalidation, and service accounts need their own controls.
5. **Upload processing can become a route into the database.** Gyazo demonstrates why parser isolation, limited runtime privileges, and restrained metadata retention matter together.
6. **Patching entry does not remove persistence.** Attacker-created credentials, sessions, altered workflows, running processes, and stolen secrets can survive a software update.
7. **Recovery needs independent evidence.** A backup that an attacker can delete, or one that has never been restored with the required keys, provides uncertain protection.
8. **Inventory includes build tools and trust stores.** Avenra's `certifi` pin is beyond the eMudhra fix, but pip, Python, OS bundles, and deployed artifacts require separate verification.

The recommended first application-hardening task remains an endpoint/object/action authorization review, with operational credential and runtime verification alongside it.

## 1. Evidence and scope

Sources prioritize vendor postmortems, maintainers' security advisories, incident responders' direct investigations, CISA, Microsoft, Mozilla, Google, and the Python security community. References are linked within each case.

- **Confirmed incident/campaign:** the source reports observed malicious activity. Its visibility and victim counts may be limited.
- **Known-exploited vulnerability:** CISA or a primary investigator establishes exploitation; that does not necessarily provide a complete victim-level incident narrative.
- **Disclosed vulnerability:** a technical flaw is established, but exploitation in the wild is not established in the reviewed material.
- **Recommended controls:** the detection and Avenra lessons below are defensive conclusions, not claims that the affected organization implemented every recommendation.

The CISA KEV snapshot consulted was catalog `2026.10.26`, containing 1,758 entries. KEV establishes known exploitation; entry date is not necessarily the first attack date. Absence from KEV does not establish safety. [CISA KEV feed][s-kev]

This is a broad research survey of documented cases, not an enumeration of every attack worldwide. Public investigations often leave the original entry route, complete exfiltration scope, or final remediation status unresolved. Those limits are recorded rather than filled with speculation.

### Case index

| # | Case and relevant dates | Main failure | Evidence/status at cutoff |
|---|---|---|---|
| 1 | LiteLLM, 10–23 October | Unrevoked exposed key; overprivileged identities; compromised release path | Confirmed malicious Python release; updated vendor attack chain |
| 2 | ConnectWise/SkyKick, October; update 26 October | Stolen application credentials and downstream tenant privileges | Confirmed campaign; initial credential exposure unresolved |
| 3 | PHP2Shell, disclosed 21 October; KEV 26 October | Unsafe OOM cleanup and stale state across worker requests | Known exploited; runtime fixes available |
| 4 | Arista VeloCloud, advisory 22 October; KEV 23 October | Authenticated SQL injection | Known exploited; fixed release trains identified |
| 5 | Ivanti Connect Secure, activity from 3 October | Authentication/routing mismatch, unsafe upload lifetime, privileged configuration trust | Confirmed zero-day chain; entry fix available; separate elevation fix not verified |
| 6 | GhostAction, October waves; report 13 October | Compromised GitHub accounts and secret-stealing workflows | Observed campaign; targeting and successful theft are different metrics |
| 7 | Gyazo, 11–12 September; final report 21 October | Command injection in content conversion; reachable database; retained metadata | Confirmed incident with revised scope |
| 8 | eMudhra/emSign, 17–26 October | Weak randomness made CA signing keys recoverable | Confirmed key compromise; malicious customer interception not established |
| 9 | EvilTokens, activity since February; report 22 September | Device-code phishing and token acquisition | Confirmed large-scale identity campaign |
| 10 | Passkey-themed social engineering, since May; report 9 September | Session capture, device-code authorization, attacker-added MFA | Confirmed campaign; passkey cryptography was not shown broken |
| 11 | SafePay, advisory 20 October | Stolen credentials, older edge/backup flaws, lateral movement | Ongoing ransomware/extortion campaign |
| 12 | DDoS, January–June; report 11 August | Network amplification and resource exhaustion | Provider telemetry; not a global census |
| 13 | Stryker, 11 March–1 April updates | Misuse of powerful endpoint-management capabilities | Confirmed disruption; initial entry unresolved |
| 14 | TanStack, 11–15 May | Untrusted PR execution, cross-trust cache poisoning, runner publishing identity | Confirmed npm supply-chain compromise |
| 15 | Clinejection/Cline CLI, February | Prompt injection into privileged automation; cache pivot; incomplete token revocation | Research demonstration plus subsequent unauthorized publication |
| 16 | Outline, advisory 25 April | Authorization checked the collection but ignored the supplied document | Disclosed cross-workspace access flaw; exploitation not established |
| 17 | React2Shell, attacks 5–7 December 2025; report 13 February 2026 | Unsafe server-side deserialization | Confirmed multi-actor compromise, reported retrospectively |
| 18 | React Server Components, advisories 14 October | Conditional RCE and CPU/memory exhaustion | New disclosures; exploitation not established in reviewed advisories |

## 2. Detailed case studies

### 1. LiteLLM: an old exposed secret became a trusted malicious release

**What happened:** `litellm==1.107.0` was maliciously published on 21 October. The vendor reported a PyPI exposure window of approximately 11:39–13:23 UTC and affected Docker tags approximately 11:46–14:20 UTC.

**Why it happened:** The vendor's 23 October attack-chain report identifies an Agent Platform master key publicly committed on 27 May. It was removed from visible history but never revoked. The key provided access to an excessively privileged GitHub organization-owner CLI OAuth token.

**Attack path:** Exposed master key → platform access on 10 October → GitHub token theft → additional token theft through CI → branch-protection bypass → release builds redirected to a lookalike repository → publication approved with another stolen identity. The resulting artifacts came through official publication channels.

**Impact:** Python startup hooks, including `cook.pth`, `cook.py`, and `sitecustomize.py`, could execute when Python started, without an application explicitly importing LiteLLM. The collector sought reachable credentials. Microsoft's analysis did not confirm execution of the optional remote second-stage payload.

**Response and recovery:** The package was removed; affected image tags were removed or repointed; publishing was locked down; GitHub access was withdrawn; organization-wide token revocation was initiated. For downstream systems that executed the release, deleting the dependency alone is insufficient: clean rebuilds, process cleanup, and rotation of reachable credentials/sessions are required. Inspection should use trusted tooling rather than starting the suspect environment's Python or pip.

**Important correction:** Earlier explanations involving a recent patched vulnerability or a Claude/log leak were superseded by the vendor's updated attack chain.

**Detection priorities:** Historical secret exposures, unexpected OAuth grants, branch/ruleset changes, release source changes, unusual runner egress, and unexpected Python startup hooks.

**Avenra lesson:** Verify revocation of the previously exposed database credential and deployment adoption of its replacement. Review GitHub, Vercel, Supabase, and provider identities for unnecessary privileges. Artifact signatures establish origin, not harmlessness; hashes only preserve the bytes that were approved.

**Sources:** [Vendor incident notice][s-litellm-incident]; [updated vendor attack chain][s-litellm-chain]; [Microsoft payload analysis][s-litellm-ms].

### 2. ConnectWise/SkyKick: application identity compromised downstream tenants

**What happened:** Attackers used compromised application credentials associated with ConnectWise/SkyKick services to access downstream Microsoft 365 environments. Microsoft's 21 October report discusses Storm-0940 and its ARTEX agentic tooling; the vendor continued response updates through 26 October.

**Why it happened:** Application identities held powerful delegated access across customer environments. App-only authentication can succeed without a human entering a password or completing an MFA prompt at the time of access.

**Attack path:** Compromised application credentials → app-only tenant access → privilege discovery and data access → additional credentials/permissions for persistence. The reviewed sources do not conclusively establish how the original application credentials were exposed.

**Impact and attribution limits:** More than 2,250 tenants were targeted; this is not a confirmed-breach count. Microsoft's observed password-spray phase had zero successful authentications and should not be presented as the proven entry mechanism. Its wider campaign observations included some intrusions reaching privileged access in under three hours; that is not a universal timing for every ConnectWise customer.

**Response and recovery:** The vendor disabled seven application identities, reset credentials/certificates, investigated tenant exposure, and pursued phased restoration. Validation remained ongoing in its 26 October update. Investigators must also review credentials and role assignments added after entry, because revoking only the original application may leave persistence.

**Detection priorities:** App-only sign-ins, added service-principal credentials, changed consent/roles, unexpected Graph activity, new privileged identities, and unusual bulk data access.

**Avenra lesson:** Service credentials need explicit scope, ownership, expiry/revocation procedures, and activity records. Human MFA does not automatically protect the database password, deployment tokens, notification credentials, or background workers.

**Sources:** [ConnectWise advisories][s-connectwise]; [Microsoft campaign analysis][s-connectwise-ms].

### 3. PHP2Shell: error handling and worker lifecycle became code execution

**Vulnerabilities:** `CVE-2026-109618` and `CVE-2026-109619`, disclosed 21 October and added to KEV on 26 October.

**Root causes:**

- `109618`: an out-of-memory early exit could leave partly initialized request state visible to shutdown processing. Cleanup could then read or branch on invalid memory.
- `109619`: request-owned error/session/extension state could survive in a persistent worker after its memory had been freed. A subsequent request could consume that stale state before ordinary initialization reset it.

**Attack path and prerequisites:** Attacker-controlled request processing → interruption or invalid lifecycle state → unsafe shutdown or a later request in the same worker → memory disclosure or code execution with the worker's privileges. Applicability differs by PHP integration, configuration, and application behavior. The OOM advisory validates complete RCE against mod_php; its FPM discussion is more qualified. The stale-state advisory validates specific mod_php and FPM paths, with application prerequisites for the latter.

**Impact:** Runtime compromise can occur below application authentication and business logic. No complete victim count was available in the reviewed material.

**Fix:** Upgrade the relevant branch to PHP **8.2.35, 8.3.36, 8.4.27, or 8.5.12**, or a later fixed release, and replace running workers. The fixes change OOM handling and reset broader request-owned state. Configuration workarounds are incomplete; broadly disabling resource protections is not an appropriate substitute for the runtime fix.

**Detection priorities:** Worker crashes/restarts, unusual memory failures and multipart traffic, unexpected child processes or egress, and post-exploitation artifacts. Absence of PHP error logs is not proof of non-exploitation.

**Avenra lesson:** These PHP flaws do not establish a vulnerability in Avenra's Flask runtime. The transferable lesson is to test failure paths, bound decoding work, and verify that worker/request state cannot leak across users. Keep runtime and parser patches current.

**Sources:** [PHP OOM advisory][s-php-oom]; [PHP stale-state advisory][s-php-state]; [CISA KEV][s-kev].

### 4. Arista VeloCloud: authentication did not prevent SQL injection

**Vulnerability:** `CVE-2026-114625`, an authenticated SQL injection affecting VeloCloud Orchestrator; vendor advisory dated 22 October, KEV entry 23 October.

**Why it happened:** An authenticated portal request could cross the SQL data/code boundary. Login is not a substitute for parameterized queries or authorization over the resulting data access.

**Attack path:** Valid portal session → vulnerable request → SQL injection → access or modification beyond the legitimate portal operation. A valid session is a prerequisite; this should not be described as unauthenticated exploitation. Public victim-specific attack narratives were limited.

**Fix:** Fixed releases include **5.2.3.18, 6.1.3.10, and 6.4.2.12** in their respective supported trains. Vendor-managed hosted/dedicated environments were reported patched. Self-managed environments need the applicable fixed release and compromise investigation where exposure warrants it.

**Detection priorities:** Unexpected database errors, anomalous query behavior, unusual portal identities, bulk reads, and changes inconsistent with ordinary administration.

**Avenra lesson:** Review every dynamic SQL boundary, including sort/filter construction and the SQLite-to-PostgreSQL adapter. Parameterize values and allowlist structural SQL choices. Limit the runtime database role so an application bug has less reach.

**Source limitation:** The advisory and CSAF endpoints returned HTTP 406 during direct retrieval; indexed vendor text and the CNA record supplied the version and prerequisite details.

**Sources:** [Arista advisory 0199][s-arista]; [CVE record][s-arista-cve]; [CISA KEV][s-kev].

### 5. Ivanti Connect Secure: several trust mismatches formed a root-access chain

**What happened:** Volexity observed exploitation beginning at least 3 October against an appliance running then-current Connect Secure 22.8R2.4. The chain was disclosed on 13 October.

**Root causes and sequence:** URL-based authorization and header-directed routing disagreed about which handler a request would reach. An uploaded file could exist before validation failed and deletion occurred. A privileged broker trusted configuration that a lower-privileged process could influence. Together these produced unauthenticated code execution followed by root privilege escalation.

**Impact:** Root access enabled credential theft, memory-only changes, and log tampering. The observed techniques could evade disk-focused integrity checks. Being on the latest available release before disclosure did not prevent this zero-day compromise.

**Fix status:** Ivanti released the entry/authentication-bypass and RCE fix tracked as `CVE-2026-104935` on 13 October. The CNA identifies fixed/unaffected builds including 22.8R2.5 and 25.1.3.0/25.1.3.1; release-train-specific vendor instructions should govern upgrades. Volexity described the separate privilege-escalation fix as pending. A newer primary-source confirmation that this separate fix shipped was not obtained by the research cutoff.

**Recovery:** Update exposed appliances, perform forensic triage, investigate downstream credential use, and rotate exposed secrets. An integrity-check pass alone does not rule out this attack.

**Detection priorities:** Appliance egress, authentication anomalies, process memory where available, downstream identity activity, and gaps or changes in logging.

**Avenra lesson:** Authorization must apply to the resolved handler and final object. Uploaded content must not become executable or accessible before validation finishes. Privileged services must not trust configuration writable by less-privileged code. Proxy/origin protections need consistent interpretation across deployment layers.

**Sources:** [Volexity investigation][s-ivanti-volexity]; [Ivanti October update][s-ivanti-vendor]; [CISA alert][s-ivanti-cisa]; [CNA record][s-ivanti-cve].

### 6. GhostAction: malicious workflows disguised as security work

**What happened:** GitGuardian's 13 October campaign update described more than 30,000 repositories targeted across roughly 3,000 users/organizations, using approximately 1,900 compromised accounts.

**Why it happened:** Control of a GitHub account or its credentials enabled changes to automation that could access repository/organization secrets. The malicious workflows presented themselves as security-audit work.

**Attack path:** Compromised GitHub access → workflow injection → CI execution → secret enumeration and history searches → exfiltration and reuse. Workflow execution occurred in 8–9 October activity; GitHub blocked later 10/12 October waves described in the report.

**Impact limits:** Targeted repositories, workflows that ran, and secrets successfully exfiltrated are separate measurements. The targeting count is not a count of confirmed breached repositories.

**Response and recovery:** Remove malicious automation, revoke the compromised GitHub credentials, and rotate downstream secrets accessible to the workflow. Deleting the workflow while leaving the original account/token usable allows reinsertion.

**Detection priorities:** Unexpected `.github/workflows` changes, newly introduced secret access, suspicious external destinations, account/SSH-key changes, and abnormal Actions runs.

**Avenra lesson:** Existing read-only workflow token permissions help, but workflow source and repository maintainers remain sensitive. Review changes to CI as security-sensitive changes and avoid making production secrets available to test jobs.

**Source:** [GitGuardian's direct campaign investigation][s-ghostaction].

### 7. Gyazo: content conversion led to database access and metadata exposure

**What happened:** Unauthorized access occurred on 11–12 September. Helpfeel's final investigation report, published 21 October, attributes entry to command injection in internally developed video/content conversion on the upload server.

**Attack path:** Malicious input to content conversion → arbitrary command execution → access to a reachable database → external transmission of data. The initial parser/process boundary failure became a much wider data incident because of what the compromised process could reach.

**Reported scope:** Approximately 23.62 million account records, 490 million image metadata records, 2.4 million filtered metadata records, and 174 million deleted-image metadata records were within the reported scope. The investigation also identified **432 actual files belonging to 133 users**. These are different record categories, not additive counts of distinct people. Large-scale theft of the underlying image files was not established. Password material was hashes, not a report of plaintext passwords.

**Uncertainty:** Missing payload logs prevented direct reconstruction of every transmitted field and exact count. Reporting the full metadata scope as that many stolen image files would overstate the findings.

**Response:** The vulnerable functionality was patched by 12 September. The company described whole-source review and high-severity fixes, authentication invalidation, tighter internal access, and owner/team-only access for legacy images. Service resumed on 27 September. A policy to automatically remove metadata 60 days after image deletion was announced, with implementation still ongoing in the final report.

**Detection priorities:** Unexpected converter subprocesses, outbound traffic from upload workers, database reads inconsistent with conversion, and unusual metadata export volume. Security event records should support scope reconstruction without indiscriminately storing sensitive upload bodies.

**Avenra lesson:** Existing JPEG decoding, limits, and private storage are useful controls. Review the privileges of the process doing that work, not just its validation function. Account for location, timestamps, filenames, case references, thumbnails, tombstones, audit events, and backups in retention decisions. Metadata can expose sensitive relationships even when photographs remain private.

**Source:** [Helpfeel/Gyazo final investigation report][s-gyazo].

### 8. eMudhra/emSign: weak CA keys affected the software trust chain

**What happened:** On 17 October, researchers reported that eight intermediate CA private keys were recoverable. Google's and Mozilla's 20 October statements document the response. The vendor's 26 October update attributes the weak keys to a script error and promises a full root-cause analysis.

**Why it mattered:** Insufficient entropy made private signing keys predictable. An attacker with a compromised CA key and an on-path position could forge a trusted certificate and intercept or modify TLS traffic for clients still trusting the affected chain.

**Evidence limit:** This is confirmed key compromise, not proof of malicious interception of customers or a breach of the CA's infrastructure. Google reported no corresponding pre-block Certificate Transparency entries establishing such abuse.

**Response:** Browsers deployed intermediate-key revocation/blocklists and root distrust measures. Google scheduled broader G3 root removal for 27 October. Affected servers need replacement certificate chains; non-browser clients need their own trust-store/runtime updates.

**Python-specific remediation:**

- `certifi` **2026.10.19+** is recommended. Version 2026.10.18 removed emSign roots; 2026.10.19 restored unaffected roots.
- Upstream `pip` **26.2.2+** updates its vendored bundle. Updating an application's separate `certifi` dependency does not update pip's copy. Distribution-patched packages require checking the distributor's security guidance.
- Python's security announcement identifies mitigated releases **3.15.2, 3.14.10, 3.13.18, 3.12.16, and 3.11.18**.
- The same announcement names updates for uv, virtualenv, conda, pixi, and sigstore where those tools are used. Images and existing environments need rebuilding/updating, not merely a change to a source manifest.

**Avenra finding:** `certifi==2026.10.23` exceeds the recommended fix. However, `.python-version` declares `3.12`, while CI selects `3.14` and the runtime lock describes a Python 3.14 environment. Exact deployed Python and pip versions were not established by reviewing these files. Verify the appropriate patched runtime and tooling, and make CI representative of deployment.

**Avenra lesson:** Preserve TLS certificate verification. Refresh the trust chain rather than bypassing verification to resolve certificate failures.

**Sources:** [Vendor update][s-emudhra]; [Mozilla][s-emudhra-mozilla]; [Google][s-emudhra-google]; [certifi advisory][s-certifi]; [Python security announcement][s-python-ca].

### 9. EvilTokens: victims authenticated on the real site for an attacker-controlled session

**What happened:** Microsoft's 22 September investigation describes device-code phishing observed since February. Its telemetry attributed more than 12,000 compromised inboxes across more than 10,000 organizations to the activity.

**Why it worked:** OAuth device authorization is intended for devices with limited input. An attacker starts a device authorization request, persuades the victim to enter its code at the legitimate identity provider, and receives the resulting authorization. The genuine login site and completed MFA can make the interaction appear trustworthy.

**Attack path:** Social-engineering lure → victim authorizes attacker-initiated device flow → attacker obtains tokens → mailbox access and persistence/data theft.

**Response and mitigation:** Block unnecessary device-code flows, constrain approved clients and device contexts, revoke affected sessions/tokens, inspect registered devices, and remove malicious mailbox rules or other persistence. Password reset alone may leave usable tokens or configuration changes.

**Detection priorities:** Unexpected device-code authentication, unfamiliar applications/devices, unusual mailbox access, forwarding rules, and token use from unexpected infrastructure.

**Avenra lesson:** Pairing/enrollment must bind the user's approval to the intended device and purpose. Treat recovery and device replacement as authentication-sensitive operations. This campaign does not show that Avenra currently implements the same OAuth flow.

**Source:** [Microsoft EvilTokens analysis][s-eviltokens].

### 10. Passkey-themed social engineering: the lure was not a cryptographic break

**What happened:** Microsoft's 9 September report describes activity observed since May using helpdesk calls, SMS, and Teams messages themed around passkey/security enrollment.

**Attack path:** Convincing support/security pretext → adversary-in-the-middle session capture or device-code authorization → attacker-added MFA methods → Graph-based enumeration and cloud data collection.

**Root cause:** The attacked boundary was user authorization and enrollment, sometimes combined with session theft. A passkey-themed message does not establish that passkey cryptography or origin binding was defeated.

**Recovery and mitigation:** Revoke sessions, reset affected credentials as appropriate, remove unauthorized authentication methods and devices, examine persistence, and harden enrollment/recovery. Phishing-resistant MFA is valuable, but alternate enrollment and recovery paths must preserve that protection.

**Detection priorities:** Authentication-method changes, unusual re-registration activity, session use after a support interaction, new devices, and atypical Graph access.

**Avenra lesson:** Preserve TOTP/MFA protections already present. Review whether password reset, MFA reset, deactivation, role change, and recovery invalidate relevant sessions and device grants. Consider phishing-resistant administrator authentication as a future improvement, with secure recovery designed alongside it.

**Source:** [Microsoft identity-compromise investigation][s-passkey].

### 11. SafePay: old weaknesses still support modern ransomware

**What happened:** The 20 October joint advisory covers investigations as recent as August 2026 and reports at least 600 victims since August 2024. That total is not limited to attacks during 2026.

**Initial access:** Exposed/stolen credentials, phishing, and older edge/backup vulnerabilities, including `CVE-2020-3259`, `CVE-2023-20269`, `CVE-2023-27532`, `CVE-2024-40711`, and `CVE-2024-40766`.

**Attack path:** Initial foothold → credential discovery and lateral movement → use of legitimate remote/admin tools → exfiltration → backup interference or destruction → encryption and extortion.

**Why it succeeds:** Patch age alone does not remove exposure. Reused credentials, broad administrative reach, and backups accessible with compromised identities let an initial foothold become organizational disruption.

**Recovery:** There is no universal completed fix for a continuing ransomware campaign. Affected environments require isolation, evidence collection, removal of persistence, credential cleanup, verified patching, and restoration from known-good backups. Restoring data without removing the attacker's access risks recurrence.

**Detection priorities:** New remote-administration tools, suspicious credential access, backup-policy changes, mass file operations, unusual archives/egress, and attempts to disable protection or recovery services.

**Avenra lesson:** Production PostgreSQL recovery must be demonstrated independently of the local SQLite backup feature. Protect backup deletion rights and key custody separately, measure data-loss and restoration targets, and test restoration into an isolated environment with outbound notifications disabled.

**Source:** [CISA/FBI and partners: SafePay advisory][s-safepay].

### 12. DDoS: upstream protection and application budgets address different limits

**What happened:** Cloudflare's 11 August report covers January–June 2026. It reports 935 network attacks above 1 Tbps and a 519% quarter-over-quarter increase for that class, with DNS/CLDAP reflection growth.

**Mechanisms:** Botnet traffic or reflected/amplified network responses can exhaust network capacity. Separately, relatively modest HTTP traffic can exhaust expensive application work, database connections, memory, queue capacity, or external-provider budgets.

**Impact limits:** These statistics describe Cloudflare's vantage, not every attack on the Internet. Many attacks are short, which favors automatic mitigation. The separate 31.4 Tbps headline published in February 2026 refers to a late-2025 attack and should not be labeled a 2026 event.

**Mitigation:** Use provider-level network/edge controls for volumetric attacks; enforce request, parsing, concurrency, timeout, queue, and spending limits for application-layer exhaustion. Neither layer substitutes for the other.

**Detection priorities:** Request-rate and concurrency shifts, endpoint cost, error rates, database wait/connection pressure, queue age, and provider cost. Monitor attempted and successful delivery separately for emergency workflows.

**Avenra lesson:** Retain identity/address rate limits and add measured resource budgets where needed. Preserve reliable emergency capture and delivery under controlled overload. The earlier hosted slowdown has no established DDoS or lock-contention diagnosis; sequential latency measurements alone cannot provide one.

**Source:** [Cloudflare H1 2026 threat report][s-ddos].

### 13. Stryker: legitimate management powers can produce destructive impact

**What happened:** Stryker reported disruption in its internal Microsoft environment on 11 March. The incident involved misuse of endpoint-management capabilities. The reviewed primary material does not establish the original access route.

**Why it matters:** A privileged management identity can perform high-impact actions through legitimate control channels. Detecting malware alone will not constrain those capabilities.

**Timeline correction:** Early statements saying there was no evidence of malware were superseded by a 23 March update confirming a malicious command-running file used to conceal activity. The company described it as non-spreading. Its 1 April update said global manufacturing was fully operational.

**Response and lessons:** CISA's 18 March guidance recommends least-privilege administrative roles, phishing-resistant MFA, privileged-access hygiene, and multi-admin approval for high-impact endpoint operations. These are CISA recommendations, not evidence that Stryker implemented every measure.

**Detection priorities:** Unusual administrative sessions, bulk endpoint actions, role changes, execution through management tools, and modifications to audit settings.

**Avenra lesson:** Broad administrator viewing/workflow access must not silently become unrestricted destructive authority. Preserve the existing explicit-assignment requirement for irreversible retention/evidence operations. Review bulk-action scope, current authorization, auditability, and recovery separately from ordinary case viewing.

**Sources:** [Stryker's dated updates][s-stryker]; [CISA endpoint-management guidance][s-stryker-cisa].

### 14. TanStack: short-lived publishing credentials did not protect a compromised runner

**What happened:** On 11 May, 84 malicious versions across 42 Router/Start monorepo packages were published. The vendor declared its containment/all-clear on 15 May.

**Root cause and chain:** Unsafe `pull_request_target` execution of untrusted code → cache poisoning across a trust boundary → code execution in a release runner → extraction of short-lived OIDC publishing credentials → malicious package publication.

**Important detail:** The attacker did not need to steal a long-lived npm token. Publication occurred even though tests failed and the normal publishing step was skipped. Once the runner was compromised, the intended workflow sequence was no longer a dependable boundary.

**Response:** Malicious versions were removed, caches purged, workflows restructured, and actions pinned to commit SHAs. Downstream users still needed to assess installed releases and rotate credentials exposed on affected machines.

**Detection priorities:** Cache writes/readers across privilege levels, untrusted checkouts in privileged events, release-runner egress, anomalous OIDC issuance, and package publications inconsistent with successful release jobs.

**Avenra lesson:** The reviewed verification workflow uses `pull_request`, read-only token permissions, SHA-pinned actions, `persist-credentials: false`, and no explicit cache reuse. Preserve these protections. Any future release workflow must avoid executing untrusted code or restoring untrusted caches while publishing privileges are available.

**Source:** [TanStack's postmortem][s-tanstack].

### 15. Clinejection: prompt injection acquired the power of the automation around it

**What happened:** A researcher demonstrated an issue-title prompt injection against a mirror of Cline's AI triage workflow. The issue content could influence an agent with powerful tools, enabling a pivot through shared Actions caches to publishing credentials. A different actor subsequently used the technique/credentials against the real project.

**Why it worked:** Untrusted issue text was processed by automation that could execute commands and influence artifacts consumed by more privileged jobs. The security boundary was the automation's capabilities and trust relationships, not simply whether its prompt asked it to behave safely.

**Response timeline:** AI workflows and release-cache usage were removed on 9 February. The wrong npm token was initially revoked, leaving the stolen token usable. On 17 February an unauthorized `cline@2.3.0` release added a post-install step that installed OpenClaw without user consent.

**Impact correction:** The vendor says the added dependency was an unrelated, non-malicious open-source package, and that other package contents matched the legitimate release. This is an unauthorized software-installation incident, not evidence that every Cline extension contained malware.

**Final remediation:** Corrected CLI version 2.4.0 was published, 2.3.0 deprecated, the actual compromised token revoked, and npm publishing moved to OIDC provenance through GitHub Actions. OIDC also needs the runner protections illustrated by TanStack.

**Detection priorities:** Unexpected agent commands, cache mutations, secret access by issue/PR jobs, and publications using credentials believed to have been revoked.

**Avenra lesson:** If AI automation is added to the repository, issue text, PR descriptions, logs, and fetched pages must remain untrusted input. Give such automation a narrow identity and toolset, without a route to production secrets or privileged release caches. Verify revocation by credential identity, not just by a similarly named token.

**Sources:** [Researcher's account and updates][s-cline-research]; [Cline's security advisory][s-cline-advisory].

### 16. Outline: a valid parent object concealed an unauthorized child

**Vulnerability:** `CVE-2026-41649` / `GHSA-23jj-rp48-w7q7`, published 25 April; affected versions `>=0.86.0,<1.7.0`; fixed in **1.7.0**.

**Root cause:** When a share-creation request included both a collection ID and document ID, authorization checked the collection but ignored the document. A share record could therefore associate the caller's permitted collection with another workspace's private document.

**Attack path:** Authenticated user with a permitted collection → request combining that collection and an unauthorized document → valid public share → document retrieval through the share. Sharing was enabled by default in affected instances.

**Impact:** Private documents and drafts could cross document and workspace boundaries. The advisory establishes the vulnerability and proof of concept; the reviewed source does not establish exploitation in the wild or a victim count.

**Fix and response:** Upgrade to the fixed release. For potentially exposed installations, review historical share creation and revoke unauthorized shares as appropriate; an application patch does not inherently invalidate share records already created.

**Detection priorities:** Parent/child ownership mismatches, unusual public-share creation, cross-workspace references, and unexpected share reads.

**Avenra lesson:** For case IDs, alert IDs, diary entries, evidence files, export items, device IDs, and queued records, validate the actual object's owner and its relationship to the authorized parent. Random IDs and hidden buttons do not provide authorization. This is the clearest model for the next cross-account review.

**Source:** [Outline maintainer advisory][s-outline].

### 17. React2Shell: one exposed server was compromised by multiple actors

**Dates:** JPCERT's 13 February 2026 report analyzes activity on 5–7 December 2025 after disclosure of `CVE-2025-55182` on 3 December 2025.

**Root cause and chain:** Unsafe React Server Components server-side deserialization → crafted unauthenticated request → remote code execution → miners/backdoors installed by multiple actors → later defacement on the investigated host.

**Why it matters:** Exploitation followed public disclosure within days, and one successful attacker did not exclude others. Finding and removing one payload would not establish the host was clean.

**Remediation:** Apply the relevant framework/runtime fixes and investigate prior exposure. Compromised hosts may require rebuilding and secret rotation, not merely an in-place package update. Use current maintainer guidance because subsequent related advisories changed the required safe versions.

**Detection priorities:** Unexpected server child processes, executable downloads, egress, persistence mechanisms, and anomalous server-function requests. Review the entire exposure window rather than only events after the most obvious payload appeared.

**Avenra lesson:** Avenra's Flask stack is not shown affected by this RSC vulnerability. The relevant lesson is rapid patch deployment plus compromise assessment for Internet-exposed execution flaws. Backend technology must be identified before applying a headline vulnerability to a project.

**Sources:** [JPCERT incident analysis][s-react-jpcert]; [React maintainer guidance][s-react-original].

### 18. October React Server Components disclosures: distinguish exposure from observed attacks

**Advisories:** `GHSA-xqc2-xf4c-x3h3` and `GHSA-h3gv-c5rc-p453`, published 14 October.

**Mechanisms:** The RCE advisory describes a rare condition involving responses transporting multiple typed arrays and an attacker-controlled value. The DoS advisory describes specially crafted server-function requests causing excessive CPU/memory use or out-of-memory failures. Their affected ranges differ; deployments should consult each advisory rather than assume a single blanket range.

**Fixes:** The maintainers list fixed `react-server-dom-webpack`, `react-server-dom-parcel`, and `react-server-dom-turbopack` releases **19.0.9, 19.1.10, 19.2.9, and 19.3.1**. The RCE advisory text formats the first as `19.0.09`; the release version is conventionally written `19.0.9`.

**Evidence limit:** The fetched advisories did not provide CVE IDs or establish in-the-wild exploitation. They should not be merged with the confirmed December 2025 React2Shell incident as though all were the same attack.

**Avenra lesson:** Framework-specific exposure depends on actual installed server components. For Avenra, the general resource-exhaustion lesson applies; an RSC-specific finding has not been established.

**Sources:** [React RCE advisory][s-react-oct-rce]; [React DoS advisory][s-react-oct-dos].

## 3. What the research establishes about Avenra

### Existing controls observed in the repository

| Area | Evidence reviewed | What it contributes |
|---|---|---|
| Authentication and MFA | `avenra/services/auth_service.py`, `avenra/services/mfa_service.py` | MFA-bound session validation, expiry/auth-version handling, TOTP replay prevention, and recovery controls |
| Request boundaries | `avenra/security.py`, `avenra/application.py` | Role guards, browser-origin/CSRF checks, device/queue identity checks, security headers, private cache controls, and request-size configuration |
| Case policy | `avenra/repositories/case_access_repository.py` | `allows()` grants administrators global viewing/workflow access; other staff use case grants |
| Irreversible operations | `avenra/services/retention_service.py` | Active-admin and explicit `assigned()` checks, bounded plans, holds, stale-plan detection, and audited cleanup |
| Upload handling | `avenra/services/diary_service.py` | JPEG decoding/verification, byte/dimension/pixel limits, v2 metadata checks, safe object naming, private storage, and checksums |
| Identity abuse controls | `avenra/services/abuse_service.py` | Keyed account/address buckets for public identity flows |
| PostgreSQL boundary | `avenra/postgres.py` | Verified TLS, transaction handling, and a global advisory lock protecting current concurrency assumptions |
| CI | `.github/workflows/verify.yml` | Read-only workflow token, SHA-pinned actions, checkout credential non-persistence, static/credential/dependency gates, SBOM generation, browser regressions |
| Recovery and retention design | `docs/stage-9-private-storage-and-recovery.md` | Documents local isolated restore evidence, key separation, bounded retention operations, and the distinction from hosted PostgreSQL recovery |

These are code/document observations. Their presence does not establish that every endpoint uses the correct guard or that production configuration matches the repository. Those are the next verification questions.

### Dependency advisory check

All **37 exact runtime pins** in `requirements-lock.txt` were submitted to the OSV batch API for the PyPI ecosystem. The response contained **no matching advisories for those declared versions** on the research date.

Selected pins:

| Package | Pinned version |
|---|---|
| Flask | 3.1.3 |
| Werkzeug | 3.1.9 |
| Gunicorn | 26.2.0 |
| Jinja2 | 3.1.6 |
| Pillow | 13.0.0 |
| cryptography | 50.0.2 |
| aiohttp | 3.14.5 |
| certifi | 2026.10.23 |
| psycopg / psycopg-binary | 3.2.13 |

For context, these pins exceed the fixes for the older Gunicorn request-smuggling issue `CVE-2024-6827` (22.0.0) and Werkzeug Windows-device-path issues `CVE-2026-21860` (3.1.5) and `CVE-2026-27199` (3.1.6). The Werkzeug issues also involve Windows-specific behavior. [Gunicorn advisory][s-gunicorn]; [Werkzeug CVE records][s-werkzeug-1]; [follow-up Werkzeug record][s-werkzeug-2]

The OSV result is a **point-in-time advisory lookup**, not proof that the deployed environment has those versions or that every package is benign. It does not cover Python/pip/OS versions, production inventory, undisclosed flaws, all malicious releases, root npm dependencies, or development/security-tool dependencies. Query endpoint: [`https://api.osv.dev/v1/querybatch`](https://api.osv.dev/v1/querybatch).

### Concrete follow-up findings

1. **Runtime declarations differ.** `.python-version` selects Python 3.12; CI selects 3.14; the lock is described as Linux/Python 3.14. Confirm the actual deployed patch version, the eMudhra mitigation, and test/deployment compatibility.
2. **Pip is a separate trust-store surface.** The reviewed build configuration invokes pip but does not explicitly establish the patched pip version. The provider may supply a fixed version; obtain build/runtime evidence rather than assuming either exposure or protection.
3. **The lock is version-pinned, not hash-locked.** Artifact hashes would improve reproducibility and byte-level integrity, but they require a trusted selection/update process and do not detect a malicious official release by themselves.
4. **The previous credential rotation is user-confirmed.** Independent evidence that the old credential is revoked and all deployment consumers use the replacement remains to be verified. The credential itself should not be copied into reports or logs.
5. **The application intentionally distinguishes viewing from deletion.** Administrators should continue seeing all alerts/cases through `allows()`. Irreversible retention/evidence operations use `assigned()` and must retain that narrower authority.
6. **Hosted recovery is a separate verification task.** Local SQLite/private-storage restore tests do not establish Supabase/PostgreSQL point-in-time recovery, required key availability, or measured production recovery time.
7. **CI has useful safeguards already.** The reviewed workflow avoids the explicit `pull_request_target`/shared-cache pattern seen in TanStack. It also audits the accessibility tooling's npm dependencies; that should not be described as an audit of every npm dependency in the repository.

## 4. Prioritized hardening work for Avenra

### Immediate operational verification

- Verify revocation and deployment adoption for the previously exposed database credential; inventory related service/deployment credentials and their scopes.
- Record actual production Python, pip, dependency, and trust-store versions, including provider-managed build tooling. For Python 3.12, verify the 3.12.16 mitigation or a documented equivalent/later supported fix; for 3.14, verify 3.14.10 or later.
- Verify recovery evidence for the hosted PostgreSQL database, private media, and required encryption keys, with an isolated restore target and disabled live notification providers.

These are verification items arising from observed context; they are not claims that production has been compromised.

### First code review: endpoint, object, and action authorization

Create a route/action inventory covering HTML routes, APIs, downloads, exports, bulk operations, background jobs, and operator commands. For every operation, identify the actor, current role, owner, parent-child relationship, required consent/device/vault state, and allowed action.

Meaningful checks should demonstrate:

- Survivor A cannot read or change survivor B's alerts, diary records, evidence, locations, devices, or queued items by replacing an identifier.
- A valid parent case cannot authorize an unrelated child object, attachment, export item, or bulk-request member.
- Unassigned non-admin staff cannot access protected cases through either direct endpoints or the UI.
- Administrators can view/work with all cases as intended, while irreversible retention remains subject to explicit assignment and existing destructive-operation checks.
- Deactivation, role/grant changes, revoked consent, and device/session revocation take effect when operations execute, including queued/retried work.
- A denied operation returns no sensitive body and causes no side effects, notification, audit-content leak, or partial bulk write.

Start with `avenra/security.py`, route/controller call sites, `case_access_repository.py`, and the services that load the final object. A role decorator alone cannot prove object ownership.

### Next: authentication lifecycle and sensitive actions

- Trace password reset, MFA recovery/reset, enrollment, invitation acceptance, device pairing/replacement, and logout through session/token invalidation.
- Confirm recovery tokens/codes are purpose-bound, short-lived or single-use as designed, and protected against concurrent replay.
- Evaluate recent-authentication requirements for credential changes, high-volume export, and irreversible actions. Keep emergency capture/delivery compatible with the application's availability requirements.
- Preserve CSRF, exact-origin checks, MFA, and rate limits. Verify reverse-proxy handling of client addresses and headers before relying on them for trust or abuse controls.

### Next: input, output, uploads, and retained metadata

- Review user-controlled SQL structure, template/HTML rendering, file paths, URL fetches, and subprocess boundaries. SSRF, stored XSS, path traversal, and command injection are review targets, not findings asserted by this report.
- Exercise decoder failures, oversized dimensions, decompression pressure, malformed JPEG metadata, interrupted storage writes, and concurrent uploads within an isolated test environment.
- Keep unvalidated uploads inaccessible; use non-executable private storage and minimum process/storage/database privileges. Introduce isolated processing if conversion or richer document formats are added.
- Treat original evidence, derived images, checksums, and transformations explicitly; silently changing retained evidence can undermine integrity tracking.
- Inventory location/timestamp/case metadata, thumbnails, audit records, orphan objects, tombstones, exports, and backup copies. Document expiry and holds for each, rather than assuming deletion of the visible item removes every copy.

### Next: database and deployment privileges

- Inspect the effective PostgreSQL role's permissions. Separate migration/administrative credentials from routine application access where feasible.
- Verify storage permissions, production-secret access, provider token scope, and which services can reach the database.
- If row-level security is considered, establish how trusted per-request identity reaches PostgreSQL. RLS does not automatically provide user isolation for a shared privileged server connection.
- Keep TLS verification enabled and define transaction/statement/connection budgets appropriate to the workload.
- Preserve the current global advisory lock until concurrency and idempotency guarantees are measured. Any lock redesign needs transaction-level evidence for duplicate delivery, lost updates, and authorization races.

### Next: CI, dependencies, and release integrity

- Review workflow and deployment changes as security-sensitive code; maintain immutable action references and limited token permissions.
- Keep untrusted PR/issue/agent execution away from production secrets, release credentials, and caches later consumed by privileged jobs.
- Establish reproducible, reviewed dependency artifacts, including hashes where supported, and inventory runtime, development, scanner, browser, Node, and OS dependencies.
- Record the artifact and dependency inventory actually deployed. Scan output for a source lock alone does not establish the production inventory.
- If publishing identities use OIDC, constrain their audience/repository/ref/environment claims and protect the runner that obtains them.

### Then: measured resilience, detection, and recovery

- Measure endpoint cost, queue age, database waits, and concurrency before changing performance controls.
- Bound body size, decoded content, per-identity/global concurrency, external calls, retries, and queue growth. Load verification should check both limits and legitimate emergency delivery.
- Record minimally necessary security events: actor identifier, action, object reference, result, timestamp, and correlation ID. Protect these records; avoid logging passwords, tokens, TOTP secrets, full evidence, or unnecessary location data.
- Alert on new admin/service credentials, MFA changes, repeated cross-object denials, bulk reads/exports, unusual storage deletion, workflow changes, and backup-policy changes.
- Exercise clean rebuild, token revocation, restore, and post-restore deletion/hold reconciliation. Measure recovery time and acceptable data loss instead of inferring them from backup existence.

## 5. What “fixed” should mean after an actual compromise

The incidents repeatedly show five different tasks:

1. **Contain entry:** disable the exposed path, malicious release, or compromised identity.
2. **Remove persistence:** inspect added credentials, factors, devices, roles, workflows, scheduled work, processes, and altered configuration.
3. **Re-establish trust:** rebuild affected execution environments and rotate reachable secrets with verified revocation.
4. **Recover service and data:** restore known-good state with required keys; account for privacy, retention, and deletion obligations when restoring old data.
5. **Validate and observe:** confirm the fix is deployed, old access fails, essential workflows function, and suspicious activity has stopped.

A package upgrade may complete only the first task. A password rotation may leave sessions. Deleting a workflow may leave the GitHub credential. Restoring a database may restore an attacker-created account. The verification must match the attack path.

## 6. Overall conclusion

Avenra already has important defensive foundations: MFA, CSRF/origin checks, private data boundaries, upload validation, rate limits, verified database TLS, constrained destructive operations, and security-oriented CI.

The highest-value next step is to **prove the boundaries between identities, objects, and actions**, then verify credential lifecycle, processing isolation, deployment privilege, and recovery. The research supports that sequence more strongly than a broad rewrite or a numerical security rating.

## Sources

All sources were consulted during this research through 27 October 2026. Incident dates and report dates are distinguished above; living vendor pages may change after this snapshot.

[s-kev]: https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json
[s-litellm-incident]: https://docs.litellm.ai/blog/security-incident-oct-21-2026
[s-litellm-chain]: https://docs.litellm.ai/blog/security-incident-oct-21-2026-attack-chain
[s-litellm-ms]: https://www.microsoft.com/en-us/security/blog/2026/10/23/inside-the-litellm-1-107-0-supply-chain-compromise-credential-theft-through-python-startup-hooks/
[s-connectwise]: https://www.connectwise.com/company/trust/advisories
[s-connectwise-ms]: https://www.microsoft.com/en-us/security/blog/2026/10/21/storm-0940-uses-artex-agentic-ai-connectwise-supply-chain-compromise/
[s-php-oom]: https://github.com/php/php-src/security/advisories/GHSA-w8hw-w9fx-j79w
[s-php-state]: https://github.com/php/php-src/security/advisories/GHSA-6wmf-4rv5-p3rp
[s-arista]: https://www.arista.com/en/support/advisories-notices/security-advisory/24838-security-advisory-0199
[s-arista-cve]: https://www.cve.org/CVERecord?id=CVE-2026-114625
[s-ivanti-volexity]: https://www.volexity.com/blog/2026/10/13/a-series-of-unauthenticated-events-chained-exploitation-of-ivanti-connect-secure-zero-days/
[s-ivanti-vendor]: https://www.ivanti.com/en-gb/blog/october-2026-security-update
[s-ivanti-cisa]: https://www.cisa.gov/news-events/alerts/2026/10/13/cisa-urges-patching-newly-exploited-vulnerability-ivanti-connect-secure
[s-ivanti-cve]: https://www.cve.org/CVERecord?id=CVE-2026-104935
[s-ghostaction]: https://blog.gitguardian.com/ghostaction-github-actions-supply-chain-attack-returns/
[s-gyazo]: https://corp.helpfeel.com/news/news-20261021-2
[s-emudhra]: https://emudhra.com/en/post/certificate-security-incident
[s-emudhra-mozilla]: https://blog.mozilla.org/security/2026/10/20/protecting-firefox-users-following-the-compromise-of-emudhra-intermediate-certificates/
[s-emudhra-google]: https://blog.google/security/protecting-chrome-and-android-users-from-compromised-emudhra-intermediate-ca-certificates
[s-certifi]: https://github.com/advisories/GHSA-6q48-6c7w-9gw2
[s-python-ca]: https://discuss.python.org/t/information-for-python-users-regarding-emudhra-emsign-ca-certificate-security-incident/109576
[s-eviltokens]: https://www.microsoft.com/en-us/security/blog/2026/09/22/unmasking-eviltokens-getting-to-the-root-of-device-code-phishing/
[s-passkey]: https://www.microsoft.com/en-us/security/blog/2026/09/09/passkey-themed-social-engineering-leads-identity-cloud-compromise/
[s-safepay]: https://www.cisa.gov/news-events/cybersecurity-advisories/aa26-293a
[s-ddos]: https://blog.cloudflare.com/ddos-threat-report-2026-h1/
[s-stryker]: https://www.stryker.com/us/en/about/news/2026/a-message-to-our-customers-03-2026.html
[s-stryker-cisa]: https://www.cisa.gov/news-events/alerts/2026/03/18/cisa-urges-endpoint-management-system-hardening-after-cyberattack-against-us-organization
[s-tanstack]: https://tanstack.com/blog/npm-supply-chain-compromise-postmortem
[s-cline-research]: https://adnanthekhan.com/posts/clinejection/
[s-cline-advisory]: https://github.com/cline/cline/security/advisories/GHSA-9ppg-jx86-fqw7
[s-outline]: https://github.com/outline/outline/security/advisories/GHSA-23jj-rp48-w7q7
[s-react-jpcert]: https://blogs.jpcert.or.jp/en/2026/02/multiple-threat-actors-rapidly-exploit-react2shell-a-case-study-of-active-compromise.html
[s-react-original]: https://react.dev/blog/2025/12/03/critical-security-vulnerability-in-react-server-components
[s-react-oct-rce]: https://github.com/react/react/security/advisories/GHSA-xqc2-xf4c-x3h3
[s-react-oct-dos]: https://github.com/react/react/security/advisories/GHSA-h3gv-c5rc-p453
[s-gunicorn]: https://nvd.nist.gov/vuln/detail/CVE-2024-6827
[s-werkzeug-1]: https://www.cve.org/CVERecord?id=CVE-2026-21860
[s-werkzeug-2]: https://www.cve.org/CVERecord?id=CVE-2026-27199
