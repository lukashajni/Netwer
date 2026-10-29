# one conversation shared by every Netwer AI panel
entries = []     # each one is {"q": str, "a": str, "actions": list}
version = 0


def add(question, answer, actions):
    global version
    entries.append({"q": question, "a": answer, "actions": list(actions or [])})
    version += 1


def clear():
    global version
    entries.clear()
    version += 1


def history():
    out = []
    for e in entries:
        out += [{"role": "user", "content": e["q"]}, {"role": "assistant", "content": e["a"]}]
    return out
