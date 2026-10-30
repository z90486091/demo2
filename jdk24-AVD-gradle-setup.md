# JDK 24 + Gradle Setup on Azure AVD (VS Code, No Admin)

- **TLDR:** Install portable JDK 24 under the user profile, set user env vars, restart VS Code, build with `gradlew`.

## Step 0: Check what already exists

- Run in VS Code terminal (PowerShell):

```powershell
java -version
echo $env:JAVA_HOME
where.exe java
where.exe gradle
dir "C:\Program Files\Java", "C:\Program Files\Eclipse Adoptium", "$env:USERPROFILE\.jdks" -ErrorAction SilentlyContinue
dir .\gradlew.bat
```

- If `gradlew.bat` exists, no separate Gradle install is needed.
- Wrapper downloads Gradle itself if `JAVA_HOME` is set and the network allows it.

## Step 1: Get JDK 24 (no admin)

- Download the JDK 24 **zip** (not MSI), e.g. Temurin 24 Windows x64 zip.
- If downloads are blocked on the AVD, download on the laptop and copy it over.
- Extract to a user-writable path with no spaces:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\tools" | Out-Null
Expand-Archive "$env:USERPROFILE\Downloads\OpenJDK24U-jdk_x64_windows_hotspot_*.zip" "$env:USERPROFILE\tools"
dir "$env:USERPROFILE\tools"
```

- Note the extracted folder name, e.g. `jdk-24.0.x+y`.

## Step 2: Set persistent user env vars

- Adjust the folder name to match Step 1:

```powershell
$jdk = "$env:USERPROFILE\tools\jdk-24.0.1+9"
[Environment]::SetEnvironmentVariable("JAVA_HOME", $jdk, "User")
$path = [Environment]::GetEnvironmentVariable("Path", "User")
[Environment]::SetEnvironmentVariable("Path", "$jdk\bin;$path", "User")
```

- GUI alternative:
  - Start → "Edit environment variables for your account"
  - New `JAVA_HOME`
  - Edit `Path`, add `%JAVA_HOME%\bin`
- If policy blocks both, use Step 3.

## Step 3: Set inside VS Code only (fallback or extra)

- Open user settings JSON: Ctrl+Shift+P → "Open User Settings (JSON)".
- Add:

```json
"terminal.integrated.env.windows": {
  "JAVA_HOME": "C:\\Users\\<USER>\\tools\\jdk-24.0.1+9",
  "PATH": "C:\\Users\\<USER>\\tools\\jdk-24.0.1+9\\bin;${env:PATH}"
},
"java.jdt.ls.java.home": "C:\\Users\\<USER>\\tools\\jdk-24.0.1+9",
"java.import.gradle.java.home": "C:\\Users\\<USER>\\tools\\jdk-24.0.1+9"
```

- Replace `<USER>` and the folder name.
- Applies to new terminals only.

## Step 4: Restart and verify

- Fully close all VS Code windows, then reopen.
- Open a **new** terminal:

```powershell
java -version
echo $env:JAVA_HOME
where.exe java
```

- Expect version 24 and a path under `tools`.

## Step 5: Check the Gradle wrapper

- Gradle must be 8.14+ to run on JDK 24.
- Check version:

```powershell
Select-String distributionUrl gradle\wrapper\gradle-wrapper.properties
```

- If older:
  - Change the URL to an 8.14+ distribution, or
  - Run `.\gradlew wrapper --gradle-version 8.14.3` with a compatible JDK.
- If there is no wrapper:
  - Install Gradle from zip into `$env:USERPROFILE\tools`.
  - Set `GRADLE_HOME`.
  - Add `%GRADLE_HOME%\bin` to `Path`.

## Step 6: Build manually

```powershell
.\gradlew.bat --version
.\gradlew.bat clean build
```

- First run downloads Gradle to `%USERPROFILE%\.gradle`.

## Step 7: Fix Zscaler / SSL download errors (if they appear)

- Symptoms:
  - `PKIX path building failed`
  - `unable to find valid certification path`
- Make Java trust the Windows cert store.
- Add to `%USERPROFILE%\.gradle\gradle.properties`:

```properties
org.gradle.jvmargs=-Djavax.net.ssl.trustStoreType=Windows-ROOT -Djavax.net.ssl.trustStore=NUL
systemProp.javax.net.ssl.trustStoreType=Windows-ROOT
```

- Also set for the wrapper download:

```powershell
[Environment]::SetEnvironmentVariable("GRADLE_OPTS", "-Djavax.net.ssl.trustStoreType=Windows-ROOT", "User")
```

- If a proxy is required, add to the same `gradle.properties`:

```properties
systemProp.http.proxyHost=<host>
systemProp.http.proxyPort=<port>
systemProp.https.proxyHost=<host>
systemProp.https.proxyPort=<port>
```

## Step 8: Make the agent see it

- Start the agent from a **new** VS Code terminal or window after Step 4.
- Sandbox policy may block the agent from reading `%USERPROFILE%\tools` or `.gradle`.
- Ask the colleague/admin to allowlist read/execute/write on:
  - the JDK folder
  - `.gradle`
  - the project folder
- Quick test in the agent terminal:
  - `java -version`
  - `.\gradlew.bat --version`

## Common errors

- `JAVA_HOME is not set`
  - Env var not applied; reopen VS Code or recheck Step 2/3.
- `Unsupported class file major version 68`
  - Gradle too old for JDK 24; fix per Step 5.
- `gradlew not recognized`
  - Use `.\gradlew.bat` in PowerShell.
- Access denied in the agent only
  - Sandbox policy issue (Step 8), not a PATH issue.
