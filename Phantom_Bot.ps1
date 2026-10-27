$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
[Net.ServicePointManager]::DefaultConnectionLimit = 10000

$BotToken  = "8502180589:AAF8jg-0u7qWH8tUcb0FF8wWczDz5ZtrztQ"
$VaultPath = "/home/tejas/Project Nexus PDF version"
$BaseWebIP = "http://192.168.29.128:8080"
$apiUrl    = "https://api.telegram.org/bot$BotToken"

# ENGINE 1: Purple Menu Registration 🟣
function Register-BotCommands {
    $cmdPayload = @{ commands = @( @{ command = "vault"; description = "📂 Open Nexus Vault Dashboard" } ) }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes(($cmdPayload | ConvertTo-Json -Depth 5 -Compress))
    try { Invoke-RestMethod -Uri "$apiUrl/setMyCommands" -Method Post -Body $bytes -ContentType "application/json; charset=utf-8" -TimeoutSec 10 | Out-Null } catch {}
}
Register-BotCommands

$Global:PathToId = @{}
$Global:IdToPath = @{}
$Global:NextId   = 1
$Global:PendingUploads = @{}

# ENGINE 2: Lightning Fast Path Hashing ⚡
function Get-PathId([string]$FullPath) {
    $clean = $FullPath.TrimEnd('\').TrimEnd('/')
    if ($Global:PathToId.ContainsKey($clean)) { return $Global:PathToId[$clean] }
    $id = "$Global:NextId"; $Global:NextId++
    $Global:PathToId[$clean] = $id; $Global:IdToPath[$id] = $clean
    return $id
}

function Get-CleanVaultItems([string]$FolderPath) {
    $ignoreFolders = @(".git", ".netlify", ".vscode", "node_modules")
    $ignoreExts    = @(".ps1", ".bat", ".html", ".js", ".vbs", ".sh")
    $ignoreNames   = @(".gitignore", "vault_index.js", "index.html")
    
    # 🛡️ THE FIX: -LiteralPath forces PowerShell to ignore brackets and symbols!
    $all = Get-ChildItem -LiteralPath $FolderPath -Force -ErrorAction SilentlyContinue | Sort-Object Name
    $folders = New-Object System.Collections.Generic.List[System.IO.DirectoryInfo]
    $files   = New-Object System.Collections.Generic.List[System.IO.FileInfo]
    
    foreach ($item in $all) {
        if ($item.Name.StartsWith(".")) { continue } 
        if ($item.PSIsContainer) {
            if ($ignoreFolders -notcontains $item.Name) { $folders.Add($item) }
        } else {
            if (($ignoreExts -notcontains $item.Extension.ToLower()) -and ($ignoreNames -notcontains $item.Name.ToLower())) { $files.Add($item) }
        }
    }
    return @{ Folders = $folders; Files = $files }
}

# ENGINE 3: Dynamic UI Generator 🖥️
function Send-VaultMenu($ChatId, [string]$FolderPath, $EditMsgId = $null) {
    # 🛡️ THE FIX applied here too!
    if (!(Test-Path -LiteralPath $FolderPath)) { return }
    
    $cleanCurrent = $FolderPath.TrimEnd('\').TrimEnd('/')
    $cleanRoot    = $VaultPath.TrimEnd('\').TrimEnd('/')
    $currentId    = Get-PathId -FullPath $cleanCurrent
    $rootId       = Get-PathId -FullPath $cleanRoot
    
    $items = Get-CleanVaultItems -FolderPath $cleanCurrent
    $rows  = New-Object System.Collections.Generic.List[object]
    
    foreach ($dir in $items.Folders) {
        $id = Get-PathId -FullPath $dir.FullName
        $row = New-Object System.Collections.Generic.List[object]
        $row.Add(@{ text = "📁 $($dir.Name)"; callback_data = "D:$id" })
        $rows.Add($row)
    }
    foreach ($file in $items.Files) {
        $id = Get-PathId -FullPath $file.FullName
        $row = New-Object System.Collections.Generic.List[object]
        $row.Add(@{ text = "📄 $($file.Name)"; callback_data = "F:$id" })
        $rows.Add($row)
    }
    if ($cleanCurrent -ne $cleanRoot) {
        $navRow = New-Object System.Collections.Generic.List[object]
        $parent = Split-Path -Path $cleanCurrent -Parent
        $parentId = Get-PathId -FullPath $parent
        $navRow.Add(@{ text = "⬅ BACK"; callback_data = "D:$parentId" })
        $navRow.Add(@{ text = "🏠 MAIN VAULT"; callback_data = "D:$rootId" })
        $rows.Add($navRow)
    }
    
    if ($Global:PendingUploads.ContainsKey($ChatId)) {
        $dropRow = New-Object System.Collections.Generic.List[object]
        $dropRow.Add(@{ text = "✅ DROP FILE IN THIS FOLDER"; callback_data = "SAVE:$currentId" })
        $rows.Add($dropRow)
        $msgText = "⚠️ <b>PENDING UPLOAD DETECTED</b>`n📍 <code>$cleanCurrent</code>"
    } else {
        $msgText = "⚡ <b>SECTOR:</b> <code>$cleanCurrent</code>"
        $utilRow = New-Object System.Collections.Generic.List[object]
        $utilRow.Add(@{ text = "🔄 REFRESH LIVE"; callback_data = "R:$currentId" })
        $rows.Add($utilRow)
    }
    
    $payload = @{ chat_id = $ChatId; text = $msgText; parse_mode = "HTML"; reply_markup = @{ inline_keyboard = $rows } }
    $endpoint = $EditMsgId ? "editMessageText" : "sendMessage"
    if ($EditMsgId) { $payload["message_id"] = $EditMsgId }
    $jsonBytes = [System.Text.Encoding]::UTF8.GetBytes(($payload | ConvertTo-Json -Depth 10 -Compress))
    try { Invoke-RestMethod -Uri "$apiUrl/$endpoint" -Method Post -Body $jsonBytes -ContentType "application/json; charset=utf-8" | Out-Null } catch {}
}

# ENGINE 4: Background Beaming (Server -> Telegram) 📤
function Send-TelegramFile($ChatId, [string]$FilePath) {
    $ThreadCode = {
        param($cId, $fPath, $url)
        try {
            $client = New-Object System.Net.Http.HttpClient
            $form   = New-Object System.Net.Http.MultipartFormDataContent
            $stream = [System.IO.File]::OpenRead($fPath)
            $form.Add((New-Object System.Net.Http.StringContent($cId)), "chat_id")
            $form.Add((New-Object System.Net.Http.StreamContent($stream)), "document", [System.IO.Path]::GetFileName($fPath))
            $null = $client.PostAsync($url, $form).Result
            $stream.Close(); $client.Dispose()
        } catch {}
    }
    $ps = [powershell]::Create().AddScript($ThreadCode).AddArgument($ChatId).AddArgument($FilePath).AddArgument("$apiUrl/sendDocument")
    $null = $ps.BeginInvoke()
}

Write-Host "[SYSTEM] PENTA-ENGINE V5 (ARMORED) ACTIVE 🚀" -ForegroundColor Green
$Offset = 0

while ($true) {
    try {
        $Updates = Invoke-RestMethod -Uri "$apiUrl/getUpdates?offset=$Offset&timeout=60" -ErrorAction Stop
        foreach ($Update in $Updates.result) {
            $Offset = $Update.update_id + 1
            
            if ($Update.callback_query) {
                $cb = $Update.callback_query
                $cbId = $cb.id
                $chatId = $cb.message.chat.id
                $msgId = $cb.message.message_id
                $data = $cb.data
                
                Invoke-RestMethod -Uri "$apiUrl/answerCallbackQuery" -Method Post -Body @{ callback_query_id = $cbId } -ErrorAction SilentlyContinue | Out-Null
                
                if ($data -match "^D:(\d+)$" -or $data -match "^R:(\d+)$") {
                    $dirPath = $Global:IdToPath[$matches[1]]
                    # 🛡️ THE FIX applied!
                    if ($dirPath -and (Test-Path -LiteralPath $dirPath)) { Send-VaultMenu -ChatId $chatId -FolderPath $dirPath -EditMsgId $msgId }
                }
                elseif ($data -match "^F:(\d+)$") {
                    $filePath = $Global:IdToPath[$matches[1]]
                    # 🛡️ THE FIX applied!
                    if ($filePath -and (Test-Path -LiteralPath $filePath)) { 
                        Invoke-RestMethod -Uri "$apiUrl/sendMessage" -Method Post -Body @{ chat_id = $chatId; text = "📡 Beaming file to you..." } | Out-Null
                        Send-TelegramFile -ChatId $chatId -FilePath $filePath 
                    }
                }
                elseif ($data -match "^SAVE:(\d+)$") {
                    $dirPath = $Global:IdToPath[$matches[1]]
                    if ($dirPath -and $Global:PendingUploads.ContainsKey($chatId)) {
                        $fileInfo = $Global:PendingUploads[$chatId]
                        $fileId = $fileInfo.fileId
                        $fileName = $fileInfo.fileName
                        $Global:PendingUploads.Remove($chatId)
                        
                        Invoke-RestMethod -Uri "$apiUrl/editMessageText" -Method Post -Body @{ chat_id = $chatId; message_id = $msgId; text = "🚀 <b>Downloading directly to Dell Server...</b>"; parse_mode = "HTML" } | Out-Null
                        
                        $DropCode = {
                            param($jFileId, $jFileName, $jDirPath, $jBotToken, $jChatId, $jVaultPath, $jBaseWeb)
                            $jApiUrl = "https://api.telegram.org/bot$jBotToken"
                            try {
                                $cleanName = $jFileName -replace '\|', '-' -replace '[<>:"?*]', ''
                                $fileReq = Invoke-RestMethod -Uri "$jApiUrl/getFile?file_id=$jFileId" -Method Get
                                $downloadUrl = "https://api.telegram.org/file/bot$jBotToken/$($fileReq.result.file_path)"
                                $dest = Join-Path $jDirPath $cleanName
                                Invoke-WebRequest -Uri $downloadUrl -OutFile $dest
                                
                                if ($dest -match "\.(docx?|pptx?|xlsx?)$") {
                                    Invoke-RestMethod -Uri "$jApiUrl/sendMessage" -Method Post -Body @{ chat_id = $jChatId; text = "⚙️ <b>Converting document to PDF in background...</b>"; parse_mode = "HTML" } | Out-Null
                                    $proc = Start-Process -FilePath "libreoffice" -ArgumentList "--headless", "--convert-to", "pdf", "`"$dest`"", "--outdir", "`"$jDirPath`"" -PassThru -Wait
                                    $dest = $dest -replace '\.(docx?|pptx?|xlsx?)$', '.pdf'
                                    $cleanName = $cleanName -replace '\.(docx?|pptx?|xlsx?)$', '.pdf'
                                }
                                
                                # 🛡️ THE FIX applied!
                                if (Test-Path -LiteralPath $dest) {
                                    $relPath = $dest.Replace($jVaultPath, "").Replace("\", "/")
                                    $urlSafeName = [uri]::EscapeDataString($relPath).Replace("%2F", "/")
                                    $webLink = "$jBaseWeb$urlSafeName"
                                    $msg = "✅ <b>UPLOAD & SYNC SUCCESSFUL</b>`n<code>$cleanName</code>`n`n🌐 <b>Check your website:</b>`n<a href='$webLink'>$webLink</a>"
                                    Invoke-RestMethod -Uri "$jApiUrl/sendMessage" -Method Post -Body @{ chat_id = $jChatId; text = $msg; parse_mode = "HTML"; disable_web_page_preview = $true } | Out-Null
                                }
                            } catch {}
                        }
                        $PentaThread = [powershell]::Create().AddScript($DropCode).AddArgument($fileId).AddArgument($fileName).AddArgument($dirPath).AddArgument($BotToken).AddArgument($chatId).AddArgument($VaultPath).AddArgument($BaseWebIP)
                        $null = $PentaThread.BeginInvoke()
                        
                        Send-VaultMenu -ChatId $chatId -FolderPath $dirPath -EditMsgId $msgId
                    }
                }
            }
            elseif ($Update.message) {
                $message = $Update.message
                $chatId  = $message.chat.id
                if ($message.document -or $message.photo) {
                    $fileId = $null
                    $fileName = "Upload_$(Get-Date -Format 'yyyyMMdd_HHmmss').pdf"
                    if ($message.document) {
                        $fileId = $message.document.file_id
                        if ($message.document.file_name) { $fileName = $message.document.file_name }
                    } elseif ($message.photo) {
                        $fileId = $message.photo[-1].file_id
                        $fileName = "Photo_$(Get-Date -Format 'yyyyMMdd_HHmmss').jpg"
                    }
                    $Global:PendingUploads[$chatId] = @{ fileId = $fileId; fileName = $fileName }
                    Send-VaultMenu -ChatId $chatId -FolderPath $VaultPath
                }
                elseif ($message.text -match "^/(vault|start)\b") {
                    $Global:PendingUploads.Remove($chatId)
                    Send-VaultMenu -ChatId $chatId -FolderPath $VaultPath
                }
            }
        }
    } catch { Start-Sleep -Milliseconds 50 } 
}