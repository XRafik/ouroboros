/** A Project room that is left keeps its content while it leaves (docs/DESIGN.md §10 "Moving between places").
 *
 * `retire(pid)` takes the room on screen out of the live instances and marks it leaving: inert, `data-leaving` (the
 * stylesheet lays it over the arriving room), and `leave()` (chat.js: no read receipt, no reading, not shown). A room
 * already hidden has nothing to show leaving and is destroyed at once. `settle(pid, inst, put)` ends that once its
 * exit has run (`put`: put away, through `destroy`, where a room holding unsendable work stays, hidden) or when it is
 * reopened meanwhile (`put` false: back among the instances, the same room); a room another one replaced meanwhile
 * is destroyed. app.js owns when; this owns what leaving is. */

export function createRoomRetirement({ instances, cancelPaint = () => {}, destroy = () => {} }) {
    const retiring = new Map();  // pid → the instance leaving the screen
    const setLeaving = (inst, leaving) => {
        inst.page.inert = leaving;
        if (leaving) { inst.page.dataset.leaving = ''; inst.leave?.(); } else { delete inst.page.dataset.leaving; inst.stay?.(); }
    };
    return {
        retiring,
        retire(pid) {
            const inst = instances.get(pid);
            if (!inst?.page || inst.page.hidden) { destroy(pid); return; }
            instances.delete(pid);
            cancelPaint(pid, inst);
            setLeaving(inst, true);
            retiring.set(pid, inst);
        },
        settle(pid, inst = retiring.get(pid), put = true) {
            if (!inst || retiring.get(pid) !== inst) return;
            retiring.delete(pid);
            setLeaving(inst, false);
            if (instances.has(pid)) { inst.destroy?.(); return; }
            instances.set(pid, inst);
            if (put) destroy(pid);
        },
    };
}
