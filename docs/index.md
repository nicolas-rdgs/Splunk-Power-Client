<p align="center" markdown>
  ![Splunk Power Client](assets/img/splunk-lightning.png){ width="320" }
</p>

<h1 style="text-align: center">Splunk Power Client</h1>

[![PyPI](https://img.shields.io/pypi/v/splunk-power-client?logo=pypi&logoColor=white)](https://pypi.org/project/splunk-power-client/)
[![Python](https://img.shields.io/badge/python-3.13%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/nicolas-rdgs/Splunk-Power-Client/blob/main/LICENSE)
[![Tests](https://github.com/nicolas-rdgs/Splunk-Power-Client/actions/workflows/test.yml/badge.svg)](https://github.com/nicolas-rdgs/Splunk-Power-Client/actions/workflows/test.yml)
[![Docs](https://github.com/nicolas-rdgs/Splunk-Power-Client/actions/workflows/docs.yml/badge.svg)](https://github.com/nicolas-rdgs/Splunk-Power-Client/actions/workflows/docs.yml)

⚡ A modern, scriptable Python client to automate everyday Splunk tasks from the command line.

📖 **Documentation:** <https://nicolas-rdgs.github.io/Splunk-Power-Client/>

💻 **Source code:** <https://github.com/nicolas-rdgs/Splunk-Power-Client>

/// warning | 🚧 Work in progress
`spc` is still under active development. Expect breaking changes, rough edges, and bugs. Use it with caution in production environments — and please [open an issue](https://github.com/nicolas-rdgs/Splunk-Power-Client/issues) if you hit one.
///

---

## 💡 What is Splunk Power Client?

**One use case `==` one command line.** That's the philosophy behind `spc` — a CLI built to **maximize your productivity** with Splunk and **get things done faster**. It turns the most common operations into scriptable, repeatable one-liners that run in seconds — speaking directly to the Splunk REST API. Bulk operations, config reloads, replays, and automation pipelines slot naturally into your scripts, terminals, and CI/CD pipelines.

## 👥 Who is it for?

- **Splunk administrators** managing instances, lookups, configs, and users
- **SOC / CERT analysts** running repetitive searches, ingestions, and dispatches
- Anyone who needs to **automate** or **script** Splunk from a terminal or CI/CD

## ✨ Key features

- Upload from **CSV, JSON or Excel** to a **Lookup CSV** or **KVStore**
- **Synchronize** a lookup from one instance to another without headaches
- **Reschedule** a batch of saved searches to refresh dashboards rapidly
- **Dispatch** saved searches in the past with trigger actions (replay)
- **Schedule** saved searches over a past time window
- Update **Splunk configurations** quickly
- Create multiple **local users** in one command

## 🚀 Quick start

1. Install

    ```sh
    pip install splunk-power-client
    ```

    Or with [uv](https://docs.astral.sh/uv/):

    ```sh
    uv tool install splunk-power-client
    ```

2. Define an instance

    ```sh
    spc instances set <NAME>
    ```

3. Check it works

    ```sh
    spc info --instance <NAME>
    ```

/// info | ☁️ Splunk Cloud
The REST API has known limitations on Splunk Cloud — `spc` has not been tested against it.
See the [Splunk REST and Cloud documentation](https://docs.splunk.com/Documentation/Splunk/9.4.2/RESTTUT/RESTandCloud).
///
