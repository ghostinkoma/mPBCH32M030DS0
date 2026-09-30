import json,sys
def daughter(I, Iusb, lugs=False):
    c=[]
    jout = (lambda k: [f"J4{k}"]) if lugs else (lambda k: ["J4"])
    jgnd = ["J5"] if lugs else ["J3"]
    c.append(dict(name="VIN J3→F1",net="VIN",src=["J3"],dst=["F1"],I=I))
    c.append(dict(name="VIN_F F1→Q9",net="VIN_F",src=["F1"],dst=["Q9"],I=I))
    for k,q in enumerate(["Q1","Q3","Q5","Q7"]):
        c.append(dict(name=f"VBUS Q9→{q}",net="VBUS",src=["Q9"],dst=[q],I=I))
    c.append(dict(name="VBUS Q10→Q1..Q7 (USB)",net="VBUS",src=["Q10"],dst=["Q1","Q3","Q5","Q7"],I=Iusb))
    for k in range(4):
        hs,ls=f"Q{2*k+1}",f"Q{2*k+2}"
        c.append(dict(name=f"SW{k} {hs}→J4",net=f"SW{k}",src=[hs],dst=jout(k),I=I))
        c.append(dict(name=f"SW{k} {ls}→J4",net=f"SW{k}",src=[ls],dst=jout(k),I=I))
        c.append(dict(name=f"SRC{k} {ls}→R{k+3}4",net=f"SRC{k}",src=[ls],dst=[f"R{k+3}4"],I=I))
        c.append(dict(name=f"ISH R{k+3}4→R70",net="ISH",src=[f"R{k+3}4"],dst=["R70"],I=I))
    c.append(dict(name="GND R70→J3/J5",net="GND",src=["R70"],dst=jgnd,I=I))
    c.append(dict(name="GND R70→J1/J2 (USB 帰路)",net="GND",src=["R70"],dst=["J1","J2"],I=Iusb))
    c.append(dict(name="USB_VBUS J1→F3",net="USB_VBUS",src=["J1"],dst=["F3"],I=Iusb))
    c.append(dict(name="USB_VBUS_P F3→Q10",net="USB_VBUS_P",src=["F3"],dst=["Q10"],I=Iusb))
    return c
k=sys.argv[1]
if k == "A": print(json.dumps(daughter(5,3)))
elif k == "B": print(json.dumps(daughter(float(sys.argv[2]) if len(sys.argv) > 2 else 10, 3, lugs=True)))
elif k=="C": print(json.dumps(daughter(3,3)))
else: print(json.dumps([dict(name="USB_VBUS J8→J1",net="USB_VBUS",src=["J8"],dst=["J1"],I=5),
                        dict(name="GND J8→J1/J2",net="GND",src=["J8"],dst=["J1","J2"],I=5)]))
