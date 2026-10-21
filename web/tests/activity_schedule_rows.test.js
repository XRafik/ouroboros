import assert from 'node:assert/strict';
import test from 'node:test';

globalThis.document = globalThis.document || { createElement: () => ({}) };
const { scheduleRowHtml } = await import('../modules/activity.js');

const standing = { id: 'daily', name: 'Daily check', enabled: true,
    trigger: { type: 'cron', expr: '0 9 * * *' }, relation: 'independent' };

test('schedule headings prefer the projected name and retain legacy fallbacks', () => {
    for (const [row, name] of [
        [{ ...standing, display_name: 'Check <results>' }, 'Check &lt;results&gt;'],
        [standing, 'Daily check'], [{ id: 'bare' }, 'bare'],
    ]) {
        assert.ok(scheduleRowHtml(row).includes(`<span class="activity-name" data-i18n-authored>${name}</span>`));
    }
});

test('task and note text is readable with a native disclosure for the complete instruction', () => {
    const text = 'Check <results>\nKeep the second line & its exact words.';
    for (const fields of [{ kind: 'task', task: { text } }, { kind: 'note', notification: { text } }]) {
        const html = scheduleRowHtml({ ...standing, ...fields });
        assert.match(html, /<details[^>]+data-schedule-text="daily">/);
        assert.match(html, /<summary[^>]*>Check &lt;results&gt;…<\/summary>/);
        assert.match(html, /Check &lt;results&gt;<br>Keep the second line &amp; its exact words\./);
        assert.doesNotMatch(html, /title=/);
        assert.match(scheduleRowHtml({ ...standing, ...fields }, true), /data-schedule-text="daily" open>/);
    }
    const short = scheduleRowHtml({ ...standing, task: { text: 'Read the report' } });
    assert.match(short, /data-i18n-authored>Read the report<\/span>/);
    assert.doesNotMatch(short, /<details/);
    assert.doesNotMatch(scheduleRowHtml(standing), /data-schedule-text/);
    const long = 'Read '.repeat(30);
    assert.match(scheduleRowHtml({ ...standing, description: long }), /<summary[^>]*>Read [^<]+…<\/summary>/);
    assert.ok(scheduleRowHtml({ ...standing, description: long }).includes(long.trim()));
});

test('waiting details are inline for the projected and legacy rows', () => {
    for (const fields of [
        { waiting_detail: { reason: 'workspace_unusable', detail: 'Choose <folder>' } },
        { waiting_detail: 'workspace_unusable: Choose <folder>' },
        { hold: { reason: 'workspace_unusable', detail: 'Choose <folder>' } },
    ]) {
        const html = scheduleRowHtml({ ...standing, ...fields });
        assert.match(html, /waiting: workspace_unusable: Choose &lt;folder&gt;<\/span>/);
        assert.doesNotMatch(html, /title=/);
    }
    assert.doesNotMatch(scheduleRowHtml(standing), /waiting:/);
    assert.match(scheduleRowHtml({ ...standing, followup_hold: { reason: 'origin_stopped', detail: 'Owner paused it' } }),
        /Original work stopped or restarted: Owner paused it/);
});

test('kind, zone and destination are visible without inventing missing addresses', () => {
    const html = scheduleRowHtml({ ...standing, kind: 'task', timezone: 'Europe/Moscow',
        destination: { project_id: 'p<1>', chat_id: 0 } });
    assert.match(html, /task · 0 9 \* \* \* \(Europe\/Moscow\)/);
    assert.match(html, /project p&lt;1&gt; · chat 0/);
    assert.match(scheduleRowHtml({ ...standing, task: { chat_id: 4 } }), / · chat 4/);
    assert.doesNotMatch(scheduleRowHtml(standing), / · (project|chat) /);
});
