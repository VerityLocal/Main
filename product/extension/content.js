// Read-only website snapshot, adapted from the original static DOM adapter.
(() => {
  const root = document.querySelector("article,main,[role=main]") || document.body;
  if (!root) return { error: "No readable website text was found" };
  const exclude = "script,style,noscript,nav,footer,header,aside,button,input,textarea,select,form,[contenteditable]:not([contenteditable=false]),[role=textbox],[role=combobox],[hidden],[aria-hidden=true]";
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const blocks = [];
  let node, previous = null, text = "";
  while ((node = walker.nextNode())) {
    const parent = node.parentElement;
    if (!parent || parent.closest(exclude)) continue;
    let hidden = false;
    for (let ancestor = parent; ancestor; ancestor = ancestor.parentElement) {
      const style = getComputedStyle(ancestor);
      if (style.display === "none" || style.visibility !== "visible" || style.opacity === "0") { hidden = true; break; }
    }
    if (hidden || !parent.getClientRects().length) continue;
    const owner = parent.closest("p,li,h1,h2,h3,h4,h5,h6,blockquote,pre,td,div") || root;
    if (owner !== previous && text.trim()) { blocks.push(text.trim()); text = ""; }
    text += node.textContent;
    previous = owner;
    if (text.length + blocks.reduce((n, value) => n + value.length, 0) > 200_000) return { error: "The active website exceeds 200,000 characters" };
  }
  if (text.trim()) blocks.push(text.trim());
  return { text: blocks.join("\n\n"), note: "Only visible read-only page text is included. Closed frames and unrendered content are not scanned." };
})();
