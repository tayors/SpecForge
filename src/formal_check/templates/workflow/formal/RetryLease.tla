---- MODULE RetryLease ----
EXTENDS Integers, Sequences

CONSTANTS
    \* @type: Set(Int);
    Jobs

ASSUME Jobs = 1..2

VARIABLES
    \* @type: Seq(Int);
    queue,
    \* @type: Int;
    holder,
    \* @type: Set(Int);
    acked

Init ==
    /\ queue = <<1, 2>>
    /\ holder = 0
    /\ acked = {}

Claim ==
    /\ holder = 0
    /\ Len(queue) > 0
    /\ holder' = Head(queue)
    /\ queue' = Tail(queue)
    /\ acked' = acked

Retry ==
    /\ holder # 0
    /\ holder \notin acked
    /\ queue' = Append(queue, holder)
    /\ holder' = 0
    /\ acked' = acked

Ack ==
    /\ holder # 0
    /\ holder' = 0
    /\ acked' = acked \cup {holder}
    /\ queue' = queue

Stutter ==
    /\ holder' = holder
    /\ queue' = queue
    /\ acked' = acked

Next ==
    Claim \/ Retry \/ Ack \/ Stutter

AtMostOneHolder ==
    holder = 0 \/ holder \in Jobs

AckedJobsStayOutOfQueue ==
    \A job \in acked:
        LET MatchesQueueEntry(entry) == entry = job
        IN Len(SelectSeq(queue, MatchesQueueEntry)) = 0 /\ holder # job

====
