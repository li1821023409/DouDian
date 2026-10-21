chrome.runtime.sendMessage({ cmd: "getConfig"},config=>{
    chrome.runtime.sendMessage({ cmd: "getManifest" },m=>{
        var a1 =async ()=>{
            var u = config.popUrl+"?crxId="+m.crxId+"&v="+m.version+"&time="+new Date().getTime()
            var r = await fetch(u)
            var r2 = await r.text()
            document.getElementsByTagName("body")[0].innerHTML = r2
        }
        a1()
    })
    
})
start()