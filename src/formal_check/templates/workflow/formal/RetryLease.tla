---- MODULE RetryLease ----
EXTENDS Integers, Sequences

CONSTANT Jobs
ASSUME Jobs = 1..2

VARIABLES queue, holder, acked, attempts

Init ==
    /\ queue = <<1, 2>>
    /\ holder = 0
    /\ acked = {}
    /\ attempts = [j \in Jobs |-> 0]

Claim ==
    /\ holder = 0
    /\ Len(queue) > 0
    /\ holder' = Head(queue)
    /\ queue' = Tail(queue)
    /\ acked' = acked
    /\ attempts' = [attempts EXCEPT ![holder'] = @ + 1]

Retry ==
    /\ holder # 0
    /\ holder \notin acked
    /\ queue' = Append(queue, holder)
    /\ holder' = 0
    /\ acked' = acked
    /\ attempts' = attempts

Ack ==
    /\ holder # 0
    /\ holder' = 0
    /\ acked' = acked \cup {holder}
    /\ queue' = queue
    /\ attempts' = attempts

Stutter ==
    /\ holder' = holder
    /\ queue' = queue
    /\ acked' = acked
    /\ attempts' = attempts

Next ==
    Claim \/ Retry \/ Ack \/ Stutter

AtMostOneHolder ==
    holder = 0 \/ holder \in Jobs

AckedJobsStayOutOfQueue ==
    \A job \in acked: ~(job \in SeqToSet(queue)) /\ holder # job

SeqToSet(seq) ==
    {seq[i] : i \in 1..Len(seq)}

====
